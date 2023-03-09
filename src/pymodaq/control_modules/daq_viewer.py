# -*- coding: utf-8 -*-
"""
Created on Wed Jan 10 16:54:14 2018

@author: Weber Sébastien
"""

from collections import OrderedDict
import copy
import datetime
import os
from pathlib import Path
import sys
from typing import List, Tuple, Union
import time

from easydict import EasyDict as edict
import numpy as np
from qtpy import QtWidgets
from qtpy.QtCore import Qt, QObject, Slot, QThread, Signal

from pymodaq.utils.data import DataRaw, DataFromPlugins, DataToExport, Axis, DataDistribution
from pymodaq.utils.logger import set_logger, get_module_name
from pymodaq.control_modules.utils import ControlModule
from pymodaq.utils.gui_utils.file_io import select_file
from pymodaq.utils.gui_utils.utils import widget_to_png_to_bytes
import pymodaq.utils.scanner
from pymodaq.utils.tcp_server_client import TCPClient
from pymodaq.utils.gui_utils.widgets.lcd import LCD
from pymodaq.utils.config import Config, get_set_local_dir
from pymodaq.utils.h5modules.browsing import browse_data
from pymodaq.utils.h5modules.saving import H5Saver
from pymodaq.utils.h5modules import module_saving
from pymodaq.utils.daq_utils import ThreadCommand
from pymodaq.utils.parameter import ioxml
from pymodaq.utils.parameter import utils as putils
from pymodaq.control_modules.viewer_utility_classes import params as daq_viewer_params
from pymodaq.utils import daq_utils as utils
from pymodaq.utils.messenger import deprecation_msg
from pymodaq.utils.gui_utils import DockArea, get_splash_sc, Dock
from pymodaq.utils.managers.parameter_manager import ParameterManager, Parameter
from pymodaq.control_modules.daq_viewer_ui import DAQ_Viewer_UI
from pymodaq.control_modules.utils import DET_TYPES, get_viewer_plugins, DAQTypesEnum
from pymodaq.utils.plotting.data_viewers.viewer import ViewerBase, ViewersEnum
from pymodaq.utils.enums import enum_checker


logger = set_logger(get_module_name(__file__))
config = Config()

local_path = get_set_local_dir()


class DAQ_Viewer(ParameterManager, ControlModule):
    """ Main PyMoDAQ class to drive detectors

    Qt object and generic UI to drive actuators. The class is giving you full functionality to select (daq_detector),
    initialize detectors (init_hardware), grab or snap data (grab_data) and save them (save_new, save_current). If
    a DockArea is given as parent widget, the full User Interface (DAQ_Viewer_UI) is loaded allowing easy control of the
    instrument.

    Attributes
    ----------
    grab_done_signal: Signal[OrderedDict]
        Signal emitted when the data from the plugin (and eventually from the data viewers) has been received. To be
        used by connected objects.
    custom_sig: Signal[ThreadCommand]
        use this to propagate info/data coming from the hardware plugin to another object
    overshoot_signal: Signal[bool]
        This signal is emitted when some 0D data from the plugin is higher than the overshoot threshold set in the
        settings

    See Also
    --------
    ControlModule, DAQ_Viewer_UI, ParameterManager

    Notes
    -----
    A particular signal from the 2D DataViewer is directly connected to the plugin: ROI_select_signal. The position and
    size of the corresponding ROI is then directly transferred to a plugin function named `ROISelect` that you have to
    create if one want to receive infos from the ROI
    """

    custom_sig = Signal(ThreadCommand)  # particular case where DAQ_Viewer  is used for a custom module

    grab_done_signal = Signal(DataToExport)

    _update_settings_signal = Signal(edict)
    overshoot_signal = Signal(bool)
    data_saved = Signal()
    grab_status = Signal(bool)

    params = daq_viewer_params

    def __init__(self, parent=None, title="Testing",
                 daq_type=config('viewer', 'daq_type'),
                 dock_settings=None, dock_viewer=None):

        self.logger = set_logger(f'{logger.name}.{title}')
        self.logger.info(f'Initializing DAQ_Viewer: {title}')

        QObject.__init__(self)
        ParameterManager.__init__(self, self.__class__.__name__)
        ControlModule.__init__(self)

        daq_type = enum_checker(DAQTypesEnum, daq_type)
        self._daq_type: DAQTypesEnum = daq_type

        self._viewer_types: List[ViewersEnum] = []
        self._viewers: List[ViewerBase] = []

        if isinstance(parent, DockArea):
            self.dockarea = parent
        else:
            self.dockarea = None

        self.parent = parent
        if parent is not None:
            self.ui: DAQ_Viewer_UI = DAQ_Viewer_UI(parent, title, daq_type=daq_type,
                                                   dock_settings=dock_settings,
                                                   dock_viewer=dock_viewer)
        else:
            self.ui: DAQ_Viewer_UI = None

        if self.ui is not None:
            QtWidgets.QApplication.processEvents()
            self.ui.add_setting_tree(self.settings_tree)
            self.ui.command_sig.connect(self.process_ui_cmds)
            self.ui.add_setting_tree(self.settings_tree)
            self.viewers = self.ui.viewers
            self._viewer_types = self.ui.viewer_types

        self.splash_sc = get_splash_sc()

        self._title = title

        self.module_and_data_saver: Union[module_saving.DetectorSaver,
                                          module_saving.DetectorEnlargeableSaver,
                                          module_saving.DetectorExtendedSaver] = None
        self.setup_saving_objects()

        self._external_h5_data = None

        self.settings.child('main_settings', 'DAQ_type').setValue(self.daq_type.name)
        self._detectors: List[str] = [det_dict['name'] for det_dict in DET_TYPES[self.daq_type.name]]
        if len(self._detectors) > 0:  # will be 0 if no valid plugins are installed
            self._detector: str = self._detectors[0]
        self.settings.child('main_settings', 'detector_type').setValue(self._detector)

        self._grabing: bool = False
        self._do_bkg: bool = False
        self._take_bkg: bool = False

        self._grab_done: bool = False
        self._start_grab_time: float = 0.  # used for the refreshing rate
        self._received_data: int = 0

        self._lcd: LCD = None

        self._bkg: List[DataFromPlugins] = None  # buffer to store background

        self._save_file_pathname: Path = None  # to store last active path, will be an Path object
        
        self._snapshot_pathname: Path = None
        self._current_data: DataToExport = None
        self._data_to_save_export: DataToExport = None

        self._do_save_data: bool = False

        self._set_setting_tree()  # to activate parameters of default Mock detector

        self.grab_done_signal.connect(self._save_export_data)

    def __repr__(self):
        return f'{self.__class__.__name__}: {self.title} ({self.daq_type}/{self.detector}'

    def setup_saving_objects(self):
        self.module_and_data_saver = module_saving.DetectorSaver(self)
        self._h5saver_continuous = H5Saver(save_type='detector')
        self._h5saver_continuous.show_settings(False)
        self._h5saver_continuous.settings.child('do_save').sigValueChanged.connect(self._init_continuous_save)
        if self.ui is not None:
            self.ui.add_setting_tree(self._h5saver_continuous.settings_tree)

    def process_ui_cmds(self, cmd: utils.ThreadCommand):
        """Process commands sent by actions done in the ui

        Parameters
        ----------
        cmd: ThreadCommand
            Possible values are:
                * init
                * quit
                * grab
                * snap
                * stop
                * show_log
                * detector_changed
                * daq_type_changed
                * save_current
                * save_new
                * do_bkg
                * take_bkg
                * viewers_changed
        """

        if cmd.command == 'init':
            self.init_hardware(cmd.attribute[0])
        elif cmd.command == 'quit':
            self.quit_fun()
        elif cmd.command == 'stop':
            self.stop()
        elif cmd.command == 'show_log':
            self.show_log()
        elif cmd.command == 'grab':
            self.grab_data(cmd.attribute, snap_state=False)
        elif cmd.command == 'snap':
            self.grab_data(False, snap_state=True)
        elif cmd.command == 'save_new':
            self.save_new()
        elif cmd.command == 'save_current':
            self.save_current()
        elif cmd.command == 'open':
            self.load_data()
        elif cmd.command == 'detector_changed':
            if cmd.attribute != '':
                self.detector_changed_from_ui(cmd.attribute)
        elif cmd.command == 'daq_type_changed':
            if cmd.attribute != '':
                self.daq_type_changed_from_ui(cmd.attribute)
        elif cmd.command == 'take_bkg':
            self.take_bkg()
        elif cmd.command == 'do_bkg':
            self.do_bkg = cmd.attribute
        elif cmd.command == 'viewers_changed':
            self._viewer_types: List[ViewersEnum] = cmd.attribute['viewer_types']
            self.viewers = cmd.attribute['viewers']

    @property
    def bkg(self):
        return self._bkg

    @property
    def viewer_docks(self):
        """:obj:`list` of Viewer Docks from the UI"""
        if self.ui is not None:
            return self.ui.viewer_docks

    def daq_type_changed_from_ui(self, daq_type: DAQTypesEnum):
        daq_type = enum_checker(DAQTypesEnum, daq_type)
        self._daq_type = daq_type
        self.settings.child('main_settings', 'DAQ_type').setValue(daq_type.name)
        self.detectors = [det_dict['name'] for det_dict in DET_TYPES[daq_type.name]]
        self.detector = self.detectors[0]

    @property
    def daq_type(self) -> DAQTypesEnum:
        """:obj:`DAQTypesEnum`: Get/Set the daq_type

        Update the detector property with the list of available detectors of a given daq_type
        """
        return self._daq_type

    @daq_type.setter
    def daq_type(self, daq_type: DAQTypesEnum):
        daq_type = enum_checker(DAQTypesEnum, daq_type)

        self._daq_type = daq_type
        if self.ui is not None:
            self.ui.daq_type = daq_type
        self.settings.child('main_settings', 'DAQ_type').setValue(daq_type.name)
        self.detectors = [det_dict['name'] for det_dict in DET_TYPES[daq_type.name]]
        self.detector = self.detectors[0]

    @property
    def daq_types(self):
        """:obj:`list` of :obj:`str`: List of available DAQ_TYPES"""
        return DAQTypesEnum.names()

    def detector_changed_from_ui(self, detector):
        self._detector = detector
        self._set_setting_tree()

    @property
    def detector(self):
        """:obj:`str`: Get/Set the detector among detectors property"""
        return self._detector

    @detector.setter
    def detector(self, det):
        if det not in self.detectors:
            raise ValueError(f'{det} is not a valid Detector: {self.detectors}')
        self._detector = det
        if self.ui is not None:
            self.ui.detector = det
        self._set_setting_tree()

    def detectors_changed_from_ui(self, detectors):
        self._detectors = detectors

    @property
    def detectors(self):
        """:obj:`list` of :obj:`str`: List of available detectors of the current daq_type"""
        return self._detectors

    @detectors.setter
    def detectors(self, detectors):
        self._detectors = detectors
        if self.ui is not None:
            self.ui.detectors = detectors

    @property
    def grab_state(self):
        """:obj:`bool`: Get the current grabbing status"""
        return self._grabing


    @property
    def do_bkg(self):
        """:obj:`bool`: Get/Set if background subtraction should be done"""
        return self._do_bkg

    @do_bkg.setter
    def do_bkg(self, doit: bool):
        self._do_bkg = doit

    @property
    def viewers(self) -> List[ViewerBase]:
        """:obj:`list` of Viewers from the UI"""
        if self.ui is not None:
            return self._viewers

    @viewers.setter
    def viewers(self, viewers):
        for viewer in self._viewers:
            try:
                viewer.data_to_export_signal.disconnect()
            except:
                pass
        for viewer in viewers:
            viewer.data_to_export_signal.connect(self._get_data_from_viewer)
            if hasattr(viewer, 'ROI_select_signal'):
                viewer.ROI_select_signal.connect(
                    lambda roi_pos_size: self.command_hardware.emit(ThreadCommand('ROISelect', roi_pos_size)))
        self._viewers = viewers

    @property
    def viewers_docks(self):
        if self.ui is not None:
            return self.ui.viewer_docks

    def quit_fun(self):
        """Quit the application, closing the hardware and other modules
        """

        # insert anything that needs to be closed before leaving

        if self._initialized_state:  # means  initialized
            self.init_hardware(False)
        self.quit_signal.emit()

        if self._lcd is not None:
            try:
                self._lcd.parent.close()
            except Exception as e:
                self.logger.exception(str(e))

        try:
            if self.ui is not None:
                self.ui.close()

        except Exception as e:
            self.logger.exception(str(e))

        if __name__ == '__main__':
            self.parent.close()

    #  #####################################
    #  Methods for running the acquisition

    def init_hardware_ui(self, do_init=True):
        """Send a command to the underlying UI to click the init button"""
        if self.ui is not None:
            self.ui.do_init()

    def init_det(self):
        deprecation_msg(f'The function *init_det* is deprecated, use init_hardware_ui')
        self.init_hardware_ui(True)

    def ini_det_fun(self):
        deprecation_msg(f'The function *ini_det_fun* is deprecated, use init_hardware')
        self.init_hardware(True)

    def init_hardware(self, do_init=True):
        """Init the selected detector

        Parameters
        ----------
        do_init: bool
            If True, create a DAQ_Detector instance and move it into a separated thread, connected its signals/slots
            to the DAQ_Viewer object (self)
            If False, force the instrument to close and kill the Thread (still not done properly in some cases)
        """
        if not do_init:
            try:
                self.command_hardware.emit(ThreadCommand(command="close"))
                QtWidgets.QApplication.processEvents()
                if self.ui is not None:
                    self.ui.detector_init = False

            except Exception as e:
                self.logger.exception(str(e))
        else:            
            try:

                hardware = DAQ_Detector(self._title, self.settings, self.detector)
                self._hardware_thread = QThread()
                if config('viewer', 'viewer_in_thread'):
                    hardware.moveToThread(self._hardware_thread)

                self.command_hardware[ThreadCommand].connect(hardware.queue_command)
                hardware.data_detector_sig[list].connect(self.show_data)
                hardware.data_detector_temp_sig[list].connect(self.show_temp_data)
                hardware.status_sig[ThreadCommand].connect(self.thread_status)
                self._update_settings_signal[edict].connect(hardware.update_settings)

                self._hardware_thread.hardware = hardware
                if config('viewer', 'viewer_in_thread'):
                    self._hardware_thread.start()
                self.command_hardware.emit(ThreadCommand("ini_detector", attribute=[
                    self.settings.child('detector_settings').saveState(), self.controller]))
                if self.ui is not None:
                    for dock in self.ui.viewer_docks:
                        dock.setEnabled(True)

            except Exception as e:
                self.logger.exception(str(e))

    def snap(self):
        """Programmatic click on the UI snap button"""
        self.grab_data(False, snap_state=True)

    def grab(self):
        """Programmatic click on the UI grab button"""
        if self.ui is not None:
            self.manage_ui_actions('grab', 'setChecked', not self._grabing)
            self.grab_data(not self._grabing, snap_state=False)

    def snapshot(self, pathname=None, dosave=False, send_to_tcpip=False):
        """Do one single grab (snap) and eventually save the data.

        Parameters
        ----------
        pathname: str or Path object
            The path where to save data
        dosave: bool
            Do save or just grab data
        send_to_tcpip: bool
            If True, send the grabed data through the TCP/IP pipe
        """
        try:
            self._do_save_data = dosave
            if pathname is None:
                raise (ValueError("filepathanme has not been defined in snapshot"))

            self._save_file_pathname = pathname
            self.grab_data(grab_state=False, send_to_tcpip=send_to_tcpip, snap_state=True)
        except Exception as e:
            self.logger.exception(str(e))

    def grab_data(self, grab_state=False, send_to_tcpip=False, snap_state=False):
        """Generic method to grab or snap data from the selected (and initialized) detector

        Parameters
        ----------
        grab_state: bool
            Defines the grab status: if True: do live grabing if False stops the grab
        send_to_tcpip: bool
            If True, send the grabed data through the TCP/IP pipe
        snap_state: bool
            if True performs a single grab
        """
        self._grabing = grab_state
        self._send_to_tcpip = send_to_tcpip
        self._grab_done = False

        if self.ui is not None:
            self.ui.data_ready = False

        self._start_grab_time = time.perf_counter()
        if snap_state:
            self.update_status(f'{self._title}: Snap')
            self.command_hardware.emit(
                ThreadCommand("single", [self.settings.child('main_settings', 'Naverage').value()]))
        else:
            if not grab_state:
                self.update_status(f'{self._title}: Stop Grab')
                self.command_hardware.emit(ThreadCommand("stop_grab", ))
            else:
                self.thread_status(ThreadCommand("update_channels", ))
                self.update_status(f'{self._title}: Continuous Grab')
                self.command_hardware.emit(
                    ThreadCommand("grab", [self.settings.child('main_settings', 'Naverage').value()]))

    def take_bkg(self):
        """Do a snap and store data to be used as background into an attribute: `self._bkg`

        The content of the bkg will be saved if data is further saved with do_bkg property set to True
        """
        self._take_bkg = True
        self.grab_data(snap_state=True)

    def stop_grab(self):
        if self.ui is not None:
            self.manage_ui_actions('grab', 'setChecked', False)
        self.stop()

    def stop(self):
        self.update_status(f'{self._title}: Stop Grab')
        self.command_hardware.emit(ThreadCommand("stop_all", ))
        self._grabing = False

    @Slot()
    def _raise_timeout(self):
        """  Print the "timeout occurred" error message in the status bar via the update_status method.
        """
        self.update_status("Timeout occured", log_type="log")

    @staticmethod
    def load_data():
        """Opens a H5 file in the H5Browser module

        Convenience static method.
        """
        browse_data()


    def save_current(self):
        """Save current data into a h5file"""
        self._do_save_data = True
        self._save_file_pathname = select_file(start_path=self._save_file_pathname, save=True,
                                                                                  ext='h5')  # see daq_utils
        self._save_export_data(self._data_to_save_export)

    def save_new(self):
        """Snap data and save them into a h5file"""
        self._do_save_data = True
        self._save_file_pathname = select_file(start_path=self._save_file_pathname, save=True,
                                                                                  ext='h5')  # see daq_utils
        self.snapshot(pathname=self._save_file_pathname, dosave=True)

    def _init_continuous_save(self):
        if self._h5saver_continuous.settings.child('do_save').value():

            self._h5saver_continuous.settings.child('base_name').setValue('Data')
            self._h5saver_continuous.settings.child('N_saved').show()
            self._h5saver_continuous.settings.child('N_saved').setValue(0)
            self.module_and_data_saver.h5saver = self._h5saver_continuous
            self._h5saver_continuous.init_file(update_h5=True)

            self.module_and_data_saver = module_saving.DetectorEnlargeableSaver(self)
            self.module_and_data_saver.h5saver = self._h5saver_continuous
            self.module_and_data_saver.get_set_node()

            self.grab_done_signal.connect(self.append_data)
        else:
            self._do_continuous_save = False
            self._h5saver_continuous.settings.child('N_saved').hide()
            self.grab_done_signal.disconnect(self.append_data)

            try:
                self._h5saver_continuous.close()
            except Exception as e:
                self.logger.exception(str(e))

    def append_data(self, where=None):
        """Appends DataToExport to a DetectorEnlargeableSaver

        Parameters
        ----------
        data: DataToExport
            The data to be added to an enlargeable h5 array

        See Also
        --------
        DetectorEnlargeableSaver
        """
        self._add_data_to_saver(self._data_to_save_export, init_step=self._h5saver_continuous.settings['N_saved'] == 0,
                                where=None)
        self._h5saver_continuous.settings.child('N_saved').setValue(self._h5saver_continuous.settings['N_saved'] + 1)

    def insert_data(self, indexes: Tuple[int], where=None, distribution=DataDistribution['uniform'],
                    save_raw_only=True):
        """Insert DataToExport to a DetectorExtendedSaver at specified indexes

        Parameters
        ----------
        indexes: tuple(int)
            The indexes within the extended array where to place these data
        where: Node or str
        distribution: DataDistribution enum
        save_raw_only: bool
            If True save only Raw data (no data processed from Roi)

        See Also
        --------
        DAQ_Scan, DetectorExtendedSaver
        """
        data = self._data_to_save_export if not save_raw_only else self._data_to_save_export.get_data_from_source('raw')
        self._add_data_to_saver(data, init_step=np.all(np.array(indexes) == 0), where=where,
                                indexes=indexes, distribution=distribution)

    def _add_data_to_saver(self, data: DataToExport, init_step=False, where=None, **kwargs):
        """Adds DataToExport data to the current node using the declared module_and_data_saver

        Parameters
        ----------
        data: DataToExport
            The data to be saved
        init_step: bool
            If True, means this is the first step of saving (if multisaving), then save background if any and a png image
        kwargs: dict
            Other named parameters to be passed as is to the module_and_data_saver

        See Also
        --------
        DetectorSaver, DetectorEnlargeableSaver, DetectorExtendedSaver

        """
        detector_node = self.module_and_data_saver.get_set_node(where)
        self.module_and_data_saver.add_data(detector_node, data, **kwargs)

        if init_step:
            if self._do_bkg and self._bkg is not None:
                self.module_and_data_saver.add_bkg(detector_node, self._bkg)

            if self._external_h5_data is not None:
                # todo test this functionnality
                self.module_and_data_saver.add_external_h5(self._external_h5_data)

    def _save_data(self, path=None, data: DataToExport = None):
        """Private. Practical implementation to save data into a h5file altogether with metadata, axes, background...

        Parameters
        ----------
        path: Path
            where to save the data as returned from browse_file for instance
        data: DataToExport

        See Also
        --------
        browse_file, _get_data_from_viewers
        """
        if path is not None:
            path = Path(path)
        h5saver = H5Saver(save_type='detector')
        h5saver.init_file(update_h5=True, custom_naming=False, addhoc_file_path=path)
        self.module_and_data_saver = module_saving.DetectorSaver(self)
        self.module_and_data_saver.h5saver = h5saver

        self._add_data_to_saver(data)

        if self.ui is not None:
            (root, filename) = os.path.split(str(path))
            filename, ext = os.path.splitext(filename)
            image_path = os.path.join(root, filename + '.png')
            self.dockarea.parent().grab().save(image_path)

        h5saver.close_file()
        self.data_saved.emit()

    @Slot(OrderedDict)
    def _save_export_data(self, data: DataToExport):
        """Auxiliary method (Slot) to receive all data (raw and processed from rois) and save them

        Parameters
        ----------
        data: DataToExport
            contains a timestamp and data (raw and extracted from roi in dataviewers) on the dorm:
            `_data_to_save_export = OrderedDict(Ndatas=Ndatas, acq_time_s=acq_time, name=name,
             control_module='DAQ_Viewer')`
             with extra keys for data dimensionality such as Data0D=OrderedDict(...)

        See Also
        --------
        _save_data
        """

        if self._do_save_data:
            self._save_data(self._save_file_pathname, data)
            self._do_save_data = False

    def _get_data_from_viewer(self, data: DataToExport):
        """Get all data emitted by the current viewers

        Each viewer *data_to_export_signal* is connected to this slot. The collected data is stored in another
        DataToExport `self._data_to_save_export` for further processing. All raw data are also stored in this attribute.
        When all viewers have emitted this signal, the collected data are emitted  with the
        `grab_done_signal` signal.

        Parameters
        ---------_
        data: DataToExport
            All data collected from the viewers

        """
        if self._data_to_save_export is not None:  # means that somehow data are not initialized so no further procsessing
            self._received_data += 1
            if len(data) != 0:
                for dat in data:
                    dat.origin = self.title
                self._data_to_save_export.append(data)

            if self._received_data == len(self.viewers):
                self._grab_done = True
                self.grab_done_signal.emit(self._data_to_save_export)

    @property
    def current_data(self) -> DataToExport:
        return self._data_to_save_export

    @Slot(list)
    def show_temp_data(self, data: List[DataFromPlugins]):
        """Send data to their dedicated viewers but those will not emit processed data signal

        Slot receiving data from plugins emitted with the `data_grabed_signal_temp`

        Parameters
        ----------
        data: list of DataFromPlugins
        """
        self._init_show_data(data)
        if self.ui is not None:
            self.set_data_to_viewers(data, temp=True)

    @Slot(list)
    def show_data(self, data: List[DataFromPlugins]):
        """Send data to their dedicated viewers but those will not emit processed data signal

        Slot receiving data from plugins emitted with the `data_grabed_signal`
        Process the data as specified in the settings, display them into the dedicated data viewers depending on the
        settings:
            * create a container (OrderedDict `_data_to_save_export`) with info from this DAQ_Viewer (title), a timestamp...
            * call `_process_data`
            * do background subtraction if any
            * check refresh time (if set in the settings) to send or not data to data viewers
            * either send to the data viewers (if refresh time is ok and/or show data option in settings is set)
            * either
                * send grab_done_signal (to the slot _save_export_data ) to save the data

        Parameters
        ----------
        data: list of DataFromPlugins

        See Also
        --------
        _init_show_data, _process_data
        """
        try:
            if self.settings.child('main_settings', 'tcpip', 'tcp_connected').value() and self._send_to_tcpip:
                self._command_tcpip.emit(ThreadCommand('data_ready', data))
            if self.ui is not None:
                self.ui.data_ready = True
            self._init_show_data(data)

            # store raw data for further processing
            self._data_to_save_export = DataToExport(self._title, control_module='DAQ_Viewer', data=data)

            if self.settings['main_settings', 'live_averaging']:
                self.settings.child('main_settings', 'N_live_averaging').setValue(self._ind_continuous_grab)
                self._current_data = copy.deepcopy(self._data_to_save_export)

                self._ind_continuous_grab += 1
                if self._ind_continuous_grab > 1:
                    self._data_to_save_export = \
                        self._data_to_save_export.average(self._current_data, self._ind_continuous_grab)

            if self._take_bkg:
                self._bkg = copy.deepcopy(self._data_to_save_export)
                self._take_bkg = False

            if self._grabing:  # if live
                refresh_time = self.settings['main_settings', 'refresh_time']
                refresh = time.perf_counter() - self._start_grab_time > refresh_time / 1000
                if refresh:
                    self._start_grab_time = time.perf_counter()
            else:
                refresh = True  # if single
            if self.ui is not None and self.settings.child('main_settings', 'show_data').value() and refresh:
                self._received_data = 0  # so that data send back from viewers can be properly counted
                data_to_plot = copy.deepcopy(self._data_to_save_export)
                # process bkg if needed
                if self.do_bkg and self._bkg is not None:
                    data_to_plot -= self._bkg
                self.set_data_to_viewers(data_to_plot.data)
            else:
                self._grab_done = True
                self.grab_done_signal.emit(self._data_to_save_export)

        except Exception as e:
            self.logger.exception(str(e))

    def _init_show_data(self, data):
        """Processing before showing data

        * process the data to check if they overshoot
        * check the data dimensionality to update the dedicated viewers

        Parameters
        ----------
        data: list of DataFromPlugins

        See Also
        --------
        _process_overshoot
        """
        self._process_overshoot(data)
        self._viewer_types = [ViewersEnum(data.dim.name) for data in data]
        if self.ui is not None:
            if self.ui.viewer_types != self._viewer_types:
                self.ui.update_viewers(self._viewer_types)

    def set_data_to_viewers(self, data, temp=False):
        """Process data dimensionality and send appropriate data to their data viewers

        Parameters
        ----------
        data: list of DataFromPlugins
        temp: bool
            if True notify the data viewers to display data as temporary (meaning not exporting processed data from roi)

        See Also
        --------
        ViewerBase, Viewer0D, Viewer1D, Viewer2D
        """
        for ind, data in enumerate(data):
            self.viewers[ind].title = data.name
            self.viewer_docks[ind].setTitle(self._title + ' ' + data.name)

            if temp:
                self.viewers[ind].show_data_temp(data)
            else:
                self.viewers[ind].show_data(data)

    def value_changed(self, param):
        """ParameterManager subclassed method. Process events from value changed by user in the UI Settings

        Parameters
        ----------
        param: Parameter
            a given parameter whose value has been changed by user
        """
        path = self.settings.childPath(param)
        if param.name() == 'DAQ_type':
            self._h5saver_continuous.settings.child('do_save').setValue(False)
            self.settings.child('main_settings', 'axes').show(param.value() == 'DAQ2D')

        elif param.name() == 'show_averaging':
            self.settings.child('main_settings', 'live_averaging').setValue(False)
            self._update_settings_signal.emit(edict(path=path, param=param, change='value'))

        elif param.name() == 'live_averaging':
            self.settings.child('main_settings', 'show_averaging').setValue(False)
            if param.value():
                self.settings.child('main_settings', 'N_live_averaging').show()
                self._ind_continuous_grab = 0
                self.settings.child('main_settings', 'N_live_averaging').setValue(0)
            else:
                self.settings.child('main_settings', 'N_live_averaging').hide()

        elif param.name() in putils.iter_children(self.settings.child('main_settings', 'axes'), []):
            if self.daq_type.name == "DAQ2D":
                if param.name() == 'use_calib':
                    if param.value() != 'None':
                        params = ioxml.XML_file_to_parameter(
                            os.path.join(local_path, 'camera_calibrations', param.value() + '.xml'))
                        param_obj = Parameter.create(name='calib', type='group', children=params)
                        self.settings.child('main_settings', 'axes').restoreState(
                            param_obj.child('axes').saveState(), addChildren=False, removeChildren=False)
                        self.settings.child('main_settings', 'axes').show()
                else:
                    for viewer in self.viewers:
                        viewer.x_axis, viewer.y_axis = self.get_scaling_options()

        elif param.name() == 'continuous_saving_opt':
            self._h5saver_continuous.show_settings(param.value())

        elif param.name() == 'wait_time':
            self.command_hardware.emit(ThreadCommand('update_wait_time', [param.value()]))

        elif param.name() == 'connect_server':
            if param.value():
                self.connect_tcp_ip()
            else:
                self._command_tcpip.emit(ThreadCommand('quit', ))

        elif param.name() == 'ip_address' or param.name == 'port':
            self._command_tcpip.emit(
                ThreadCommand('update_connection', dict(ipaddress=self.settings.child('main_settings', 'tcpip',
                                                                                      'ip_address').value(),
                                                        port=self.settings.child('main_settings', 'tcpip',
                                                                                 'port').value())))

        if path is not None:
            if 'main_settings' not in path:
                self._update_settings_signal.emit(edict(path=path, param=param, change='value'))

                if self.settings.child('main_settings', 'tcpip', 'tcp_connected').value():
                    self._command_tcpip.emit(ThreadCommand('send_info', dict(path=path, param=param)))

    def param_deleted(self, param):
        """ParameterManager subclassed method. Process events from parameter deleted by user in the UI Settings

        Parameters
        ----------
        param: Parameter
            a given parameter whose value has been changed by user
        """
        if param.name() not in putils.iter_children(self.settings.child('main_settings'), []):
            self._update_settings_signal.emit(edict(path=['detector_settings'], param=param, change='parent'))

    def _set_setting_tree(self):
        """Apply the specific settings of the selected detector (plugin)

        Remove previous ones and load on the fly the new ones

        See Also
        --------
        pymodaq.control_modules.utils:get_viewer_plugins
        """

        try:
            if len(self.settings.child('detector_settings').children()) > 0:
                for child in self.settings.child('detector_settings').children():
                    child.remove()

            det_params, _class = get_viewer_plugins(self.daq_type.name, self.detector)
            self.settings.child('detector_settings').addChildren(det_params.children())
        except Exception as e:
            self.logger.exception(str(e))

    def _process_overshoot(self, data):
        """Compare data value (0D) to the given overshoot setting
        """
        if self.settings.child('main_settings', 'overshoot', 'stop_overshoot').value():
            for channels in data:
                for channel in channels['data']:
                    if any(channel >= self.settings.child('main_settings', 'overshoot', 'overshoot_value').value()):
                        self.overshoot_signal.emit(True)

    def get_scaling_options(self):
        """Create axes scaling options depending on the ('main_settings', 'axes') settings

        Returns
        -------
        pymodaq.utils.data.ScalingOptions
        """
        scaled_xaxis = Axis(label=self.settings['main_settings', 'axes', 'xaxis', 'xlabel'],
                            units=self.settings['main_settings', 'axes', 'xaxis', 'xunits'],
                            offset=self.settings['main_settings', 'axes', 'xaxis', 'xoffset'],
                            scaling=self.settings['main_settings', 'axes', 'xaxis', 'xscaling'])
        scaled_yaxis = Axis(label=self.settings['main_settings', 'axes', 'yaxis', 'ylabel'],
                            units=self.settings['main_settings', 'axes', 'yaxis', 'yunits'],
                            offset=self.settings['main_settings', 'axes', 'yaxis', 'yoffset'],
                            scaling=self.settings['main_settings', 'axes', 'yaxis', 'yscaling'])
        return scaled_xaxis, scaled_yaxis

    @Slot(ThreadCommand)
    def thread_status(self, status):
        """Get back info (using the ThreadCommand object) from the hardware

        And re-emit this ThreadCommand using the custom_sig signal if it should be used in a higher level module

        Parameters
        ----------
        status: ThreadCommand
            The info returned from the hardware, the command (str) can be either:
                * Update_Status: display messages and log info
                * ini_detector: update the status with "detector initialized" value and init state if attribute not null.
                * close: close the current thread and delete corresponding attribute on cascade.
                * grab : emit grab_status(True)
                * grab_stopped: emit grab_status(False)
                * x_axis: update x_axis from status attribute and User Interface viewer consequently. (Deprecated)
                * y_axis: update y_axis from status attribute and User Interface viewer consequently. (Deprecated)
                * update_channel: update the viewer channels in case of 0D DAQ_type (deprecated)
                * update_settings: Update the "detector setting" node in the settings tree.
                * update_main_settings: update the "main setting" node in the settings tree
                * raise_timeout:
                * show_splash: Display the splash screen with attribute as message
                * close_splash
                * init_lcd: display a LCD panel
                * lcd: display on the LCD panel, the content of the attribute
                * stop: stop the grab
        """
        if status.command == "Update_Status":
            if len(status.attribute) > 1:
                self.update_status(status.attribute[0], log=status.attribute[1])
            else:
                self.update_status(status.attribute[0])

        elif status.command == "ini_detector":
            self.update_status("detector initialized: " + str(status.attribute[0]['initialized']))
            if self.ui is not None:
                self.ui.detector_init = status.attribute[0]['initialized']
            if status.attribute[0]['initialized']:
                self.controller = status.attribute[0]['controller']
                self._initialized_state = True
            else:
                self._initialized_state = False

            self.init_signal.emit(self._initialized_state)

        elif status.command == "close":
            try:
                self.update_status(status.attribute[0])
                self._hardware_thread.quit()
                self._hardware_thread.wait()
                finished = self._hardware_thread.isFinished()
                if finished:
                    pass
                else:
                    print('Thread still running')
                    self._hardware_thread.terminate()
                    self.update_status('thread is locked?!', 'log')
            except Exception as e:
                self.logger.exception(str(e))

            self._initialized_state = False
            self.init_signal.emit(self._initialized_state)

        elif status.command == "grab":
            self.grab_status.emit(True)

        elif status.command == 'grab_stopped':
            self.grab_status.emit(False)

        elif status.command == "x_axis":
            deprecation_msg(f'using emit_x_axis in plugins is deprecated use data emission with correct axis to set it.'
                            f'To send it only once, use the data_grabed_signal_temp')

        elif status.command == "y_axis":
            deprecation_msg(f'using emit_y_axis in plugins is deprecated use data emission with correct axis to set it.'
                            f'To send it only once, use the data_grabed_signal_temp')

        elif status.command == "update_channels":
            pass

        elif status.command == 'update_main_settings':
            # this is a way for the plugins to update main settings of the ui (solely values, limits and options)
            try:
                if status.attribute[2] == 'value':
                    self.settings.child('main_settings', *status.attribute[0]).setValue(status.attribute[1])
                elif status.attribute[2] == 'limits':
                    self.settings.child('main_settings', *status.attribute[0]).setLimits(status.attribute[1])
                elif status.attribute[2] == 'options':
                    self.settings.child('main_settings', *status.attribute[0]).setOpts(**status.attribute[1])
            except Exception as e:
                self.logger.exception(str(e))

        elif status.command == 'update_settings':
            # using this the settings shown in the UI for the plugin reflects the real plugin settings
            try:
                self.settings.sigTreeStateChanged.disconnect(
                    self.parameter_tree_changed)  # any changes on the detcetor settings will update accordingly the gui
            except Exception as e:
                self.logger.exception(str(e))
            try:
                if status.attribute[2] == 'value':
                    self.settings.child('detector_settings', *status.attribute[0]).setValue(status.attribute[1])
                elif status.attribute[2] == 'limits':
                    self.settings.child('detector_settings', *status.attribute[0]).setLimits(status.attribute[1])
                elif status.attribute[2] == 'options':
                    self.settings.child('detector_settings', *status.attribute[0]).setOpts(**status.attribute[1])
                elif status.attribute[2] == 'childAdded':
                    child = Parameter.create(name='tmp')
                    child.restoreState(status.attribute[1][0])
                    self.settings.child('detector_settings', *status.attribute[0]).addChild(status.attribute[1][0])

            except Exception as e:
                self.logger.exception(str(e))
            self.settings.sigTreeStateChanged.connect(self.parameter_tree_changed)

        elif status.command == 'raise_timeout':
            self._raise_timeout()

        elif status.command == 'show_splash':
            self.ui.settings_tree.setEnabled(False)
            self.splash_sc.show()
            self.splash_sc.raise_()
            self.splash_sc.showMessage(status.attribute[0], color=Qt.white)

        elif status.command == 'close_splash':
            self.splash_sc.close()
            self.ui.settings_tree.setEnabled(True)

        elif status.command == 'init_lcd':
            if self._lcd is not None:
                try:
                    self._lcd.parent.close()
                except Exception as e:
                    self.logger.exception(str(e))
            # lcd module
            lcd = QtWidgets.QWidget()
            self._lcd = LCD(lcd, **status.attribute[0])
            lcd.setVisible(True)
            QtWidgets.QApplication.processEvents()

        elif status.command == 'lcd':
            self._lcd.setvalues(status.attribute[0])

        elif status.command == 'stop':
            self.stop()

        self.custom_sig.emit(status)  # to be used if needed in custom application connected to this module

    def connect_tcp_ip(self):
        """Init a TCPClient in a separated thread to communicate with a distant TCp/IP Server

        Use the settings: ip_adress and port to specify the connection

        See Also
        --------
        TCPServer
        """
        if self.settings.child('main_settings', 'tcpip', 'connect_server').value():
            self._tcpclient_thread = QThread()

            tcpclient = TCPClient(self.settings.child('main_settings', 'tcpip', 'ip_address').value(),
                                  self.settings.child('main_settings', 'tcpip', 'port').value(),
                                  self.settings.child('detector_settings'))
            tcpclient.moveToThread(self._tcpclient_thread)
            self._tcpclient_thread.tcpclient = tcpclient
            tcpclient.cmd_signal.connect(self.process_tcpip_cmds)

            self._command_tcpip[ThreadCommand].connect(tcpclient.queue_command)

            self._tcpclient_thread.start()
            tcpclient.init_connection(extra_commands=[ThreadCommand('get_axis', )])

    @Slot(ThreadCommand)
    def process_tcpip_cmds(self, status):
        """Receive commands from the TCP Server (if connected) and process them

        Parameters
        ----------
        status: ThreadCommand
            Possible commands are:
            * 'Send Data: to trigger a snapshot
            * 'connected': show that connection is ok
            * 'disconnected': show that connection is not OK
            * 'Update_Status': update a status command
            * 'set_info': receive settings from the server side and update them on this side
            * 'get_axis': request the plugin to send its axis info


        See Also
        --------
        connect_tcp_ip, TCPServer

        """
        if 'Send Data' in status.command:
            self.snapshot('', send_to_tcpip=True)
        elif status.command == 'connected':
            self.settings.child('main_settings', 'tcpip', 'tcp_connected').setValue(True)

        elif status.command == 'disconnected':
            self.settings.child('main_settings', 'tcpip', 'tcp_connected').setValue(False)

        elif status.command == 'Update_Status':
            self.thread_status(status)

        elif status.command == 'set_info':
            param_dict = ioxml.XML_string_to_parameter(status.attribute[1])[0]
            param_tmp = Parameter.create(**param_dict)
            param = self.settings.child('detector_settings', *status.attribute[0][1:])

            param.restoreState(param_tmp.saveState())

        elif status.command == 'get_axis':
            self.command_hardware.emit(
                ThreadCommand('get_axis', ))  # tells the plugin to emit its axes so that the server will receive them


class DAQ_Detector(QObject):
    """
        ========================= ==========================
        **Attributes**              **Type**
        *status_sig*                instance of pyqt Signal
        *data_detector_sig*         instance of pyqt Signal
        *data_detector_temp_sig*    instance of pyqt Signal

        *waiting_for_data*          boolean
        *controller*                ???
        *detector_name*             string
        *detector*                  ???
        *controller_adress*         ???
        *grab_state*                boolean
        *single_grab*               boolean
        *x_axis*                    1D numpy array
        *y_axis*                    1D numpy array
        *datas*                     dictionnary
        *ind_average*               int
        *Naverage*                  int
        *average_done*              boolean
        *hardware_averaging*        boolean
        *show_averaging*            boolean
        *wait_time*                 int
        *daq_type*                  string
        ========================= ==========================
    """
    status_sig = Signal(ThreadCommand)
    data_detector_sig = Signal(list)
    data_detector_temp_sig = Signal(list)

    def __init__(self, title, settings_parameter, detector_name):
        super().__init__()
        self.waiting_for_data = False
        self.controller = None
        self.logger = set_logger(f'{logger.name}.{title}.detector')
        self.detector_name = detector_name
        self.detector = None
        self.controller_adress = None
        self.grab_state = False
        self.single_grab = False
        self.datas = None
        self.ind_average = 0
        self.Naverage = None
        self.average_done = False
        self.hardware_averaging = False
        self.show_averaging = False
        self.wait_time = settings_parameter['main_settings', 'wait_time']
        self.daq_type = DAQTypesEnum[settings_parameter['main_settings', 'DAQ_type']]

    @Slot(edict)
    def update_settings(self, settings_parameter_dict):
        """
            | Set attribute values in case of "main_settings" path with corresponding parameter values.
            | Recursively call the method on detector class attribute else.

            ======================== ============== ======================================
            **Parameters**             **Type**      **Description**
            settings_parameter_dict    dictionnary   the (pathname,parameter) dictionnary
            ======================== ============== ======================================

            See Also
            --------
            update_settings
        """

        path = settings_parameter_dict['path']
        param = settings_parameter_dict['param']
        if path[0] == 'main_settings':
            if hasattr(self, path[-1]):
                setattr(self, path[-1], param.value())

        elif path[0] == 'detector_settings':
            self.detector.update_settings(settings_parameter_dict)

    @Slot(ThreadCommand)
    def queue_command(self, command: ThreadCommand):
        """Transfer command from the main module to the hardware module

        Parameters
        ----------
        command: ThreadCommand
            The specific (or generic) command (str) to pass to the hardware,  either:
            * ini_detector
            * close
            * grab
            * single
            * stop_grab
            * stop_all
            * update_scanner
            * move_at_navigator
            * update_com
            * update_wait_time
            * get_axis
            * any string that the hardware is able to understand
        """
        if command.command == "ini_detector":
            status = self.ini_detector(*command.attribute)
            self.status_sig.emit(ThreadCommand(command.command, [status, 'log']))

        elif command.command == "close":
            status = self.close()
            self.status_sig.emit(ThreadCommand(command.command, [status, 'log']))

        elif command.command == "grab":
            self.single_grab = False
            self.grab_state = True
            self.grab_data(*command.attribute)

        elif command.command == "single":
            self.single_grab = True
            self.grab_state = True
            self.single(*command.attribute)

        elif command.command == "stop_grab":
            self.grab_state = False
            self.status_sig.emit(ThreadCommand("Update_Status", ['Stoping grab']))

        elif command.command == "stop_all":
            self.grab_state = False
            self.detector.stop()
            QtWidgets.QApplication.processEvents()
            self.status_sig.emit(ThreadCommand("Update_Status", ['Stoping grab']))

        elif command.command == 'update_scanner':
            self.detector.update_scanner(command.attribute[0])

        elif command.command == 'move_at_navigator':
            self.detector.move_at_navigator(*command.attribute)

        elif command.command == 'update_com':
            self.detector.update_com()

        elif command.command == 'update_wait_time':
            self.wait_time = command.attribute[0]

        elif command.command == 'get_axis':
            self.detector.get_axis()

        else:  # custom commands for particular plugins (see ROISelect in relation to a Viewer2D and the plugin
            # Mock2D or the spectrometer module 'get_spectro_wl' for instance)
            if hasattr(self.detector, command.command):
                cmd = getattr(self.detector, command.command)
                cmd(command.attribute)

    def ini_detector(self, params_state=None, controller=None):
        """
            Init the detector from params_state parameter and DAQ_type class attribute :
                * in **0D** profile : update the local status and send the "x_axis" Thread command via a status signal
                * in **1D** profile : update the local status and send the "x_axis" Thread command via a status signal
                * in **2D** profile : update the local status and send the "x_axis" and the "y_axis" Thread command via a status signal

            =============== =========== ==========================================
            **Parameters**    **Type**    **Description**
            *params_state*     ???         the parameter's state of initialization
            =============== =========== ==========================================

            See Also
            --------
            ini_detector, daq_utils.ThreadCommand
        """
        try:
            # status="Not initialized"
            status = edict(initialized=False, info="", x_axis=None, y_axis=None)
            det_params, class_ = get_viewer_plugins(self.daq_type.name, self.detector_name)
            self.detector = class_(self, params_state)

            try:
                self.detector.data_grabed_signal.connect(self.data_ready)
                self.detector.data_grabed_signal_temp.connect(self.emit_temp_data)
                infos = self.detector.ini_detector(controller)  # return edict(info="", controller=, stage=)
                status.controller = self.detector.controller

            except Exception as e:
                logger.exception('Hardware couldn\'t be initialized' + str(e))
                infos = str(e), False
                status.controller = None

            if isinstance(infos, edict):
                status.update(infos)
            else:
                status.info = infos[0]
                status.initialized = infos[1]


            if status['x_axis'] is not None:
                x_axis = status['x_axis']
                self.status_sig.emit(ThreadCommand("x_axis", [x_axis]))
            if status['y_axis'] is not None:
                y_axis = status['y_axis']
                self.status_sig.emit(ThreadCommand("y_axis", [y_axis]))

            self.hardware_averaging = class_.hardware_averaging  # to check if averaging can be done directly by the hardware or done here software wise

            return status
        except Exception as e:
            self.logger.exception(str(e))
            return status

    @Slot(list)
    def emit_temp_data(self, datas):
        self.data_detector_temp_sig.emit(datas)

    @Slot(list)
    def data_ready(self, datas):
        """
            | Update the local datas attribute from the given datas parameter if the averaging has to be done software wise.
            |
            | Else emit the data detector signals with datas parameter as an attribute.

            =============== ===================== =========================
            **Parameters**    **Type**             **Description**
            *datas*           list                the datas to be emitted.
            =============== ===================== =========================

            See Also
            --------
            daq_utils.ThreadCommand
        """

        # datas validation check for backcompatibility with plugins not exporting new DataFromPlugins list of objects

        for dat in datas:
            if not isinstance(dat, DataFromPlugins):
                if 'type' in dat:
                    dat['dim'] = dat['type']
                    dat['type'] = 'raw'

        if not self.hardware_averaging:  # to execute if the averaging has to be done software wise
            self.ind_average += 1
            if self.ind_average == 1:
                self.datas = datas
            else:
                try:
                    for indpannel, dic in enumerate(datas):
                        self.datas[indpannel]['data'] = \
                            [((self.ind_average - 1) * self.datas[indpannel]['data'][ind] + datas[indpannel]['data'][
                                ind]) / self.ind_average for ind in range(len(datas[indpannel]['data']))]

                    if self.show_averaging:
                        self.emit_temp_data(self.datas)

                except Exception as e:
                    self.logger.exception(str(e))

            if self.ind_average == self.Naverage:
                self.average_done = True
                self.data_detector_sig.emit(self.datas)
                self.ind_average = 0
        else:
            self.data_detector_sig.emit(datas)
        self.waiting_for_data = False
        if not self.grab_state:
            # self.status_sig.emit(["Update_Status","Grabing braked"])
            self.detector.stop()

    def single(self, Naverage=1, args_as_dict={}):
        """
            Call the grab method with Naverage parameter as an attribute.

            =============== =========== ==================
            **Parameters**    **Type**    **Description**
            *Naverage*        int
            *savepath*           str        eventual savepath
            =============== =========== ==================

            See Also
            --------
            daq_utils.ThreadCommand, grab
        """
        try:
            self.grab_data(Naverage, live=False, **args_as_dict)

        except Exception as e:
            self.logger.exception(str(e))

    def grab_data(self, Naverage=1, live=True, **kwargs):
        """
            | Update status with 'Start Grabing' Update_status sub command of the Thread command.
            | Process events and grab naverage is needed.

            =============== =========== ==================
            **Parameters**    **Type**    **Description**
            *Naverage*        int
            =============== =========== ==================

            See Also
            --------
            daq_utils.ThreadCommand, grab
        """
        try:
            self.ind_average = 0
            self.Naverage = Naverage
            if Naverage > 1:
                self.average_done = False
            # self.status_sig.emit(ThreadCommand("Update_Status", [f'Start Grabing']))
            self.waiting_for_data = False

            # for live mode:two possibilities: either snap one data and regrab softwarewise (while True) or if
            # self.detector.live_mode_available is True all data is continuously emited from the plugin
            if self.detector.live_mode_available:
                kwargs['wait_time'] = self.wait_time
            else:
                kwargs['wait_time'] = 0
            self.status_sig.emit(ThreadCommand('grab'))
            while True:
                try:
                    if not self.waiting_for_data:
                        self.waiting_for_data = True
                        self.detector.grab_data(Naverage, live=live, **kwargs)
                    QtWidgets.QApplication.processEvents()
                    if self.single_grab:
                        if self.hardware_averaging:
                            break
                        else:
                            if self.average_done:
                                break
                    else:
                        QThread.msleep(self.wait_time) #if in live mode apply a waiting time after acquisition
                    if not self.grab_state:
                        break
                    if self.detector.live_mode_available:
                        break
                except Exception as e:
                    self.logger.exception(str(e))
            self.status_sig.emit(ThreadCommand('grab_stopped'))

        except Exception as e:
            self.logger.exception(str(e))

    def close(self):
        """
            close the current instance of DAQ_Detector.
        """
        try:
            self.detector.stop()
            status = self.detector.close()
        except Exception as e:
            self.logger.exception(str(e))
            status = str(e)
        return status


def prepare_docks(area, title):
    dock_settings = Dock(title + " settings", size=(150, 250))
    dock_viewer = Dock(title + " viewer", size=(350, 350))
    area.addDock(dock_settings)
    area.addDock(dock_viewer, 'right', dock_settings)
    return dict(dock_settings=dock_settings, dock_viewer=dock_viewer)


def main(init_qt=True, init_det=False):
    if init_qt:  # used for the test suite
        app = QtWidgets.QApplication(sys.argv)
        if config('style', 'darkstyle'):
            import qdarkstyle
            app.setStyleSheet(qdarkstyle.load_stylesheet(qdarkstyle.DarkPalette))

    win = QtWidgets.QMainWindow()
    area = DockArea()
    win.setCentralWidget(area)
    win.resize(1000, 500)
    win.setWindowTitle('PyMoDAQ Viewer')
    win.show()

    title = "Testing"
    viewer = DAQ_Viewer(area, title="Testing", daq_type=config('viewer', 'daq_type'),
                        **prepare_docks(area, title))
    if init_det:
        viewer.init_hardware_ui(init_det)

    if init_qt:
        sys.exit(app.exec_())
    return viewer, win


if __name__ == '__main__':
    main(init_det=False)
