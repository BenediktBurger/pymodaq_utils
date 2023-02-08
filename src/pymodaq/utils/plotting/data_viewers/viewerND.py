from abc import ABCMeta, abstractmethod, abstractproperty
import sys
from typing import List, Tuple, Union

import numpy as np
from qtpy import QtWidgets
from qtpy.QtCore import QObject, Slot, Signal, QRectF, QPointF

from pymodaq.utils.logger import set_logger, get_module_name
from pymodaq.utils.gui_utils.dock import DockArea, Dock
from pymodaq.utils.plotting.data_viewers.viewer1D import Viewer1D
from pymodaq.utils.plotting.utils.axes_viewer import AxesViewer
from pymodaq.utils.plotting.data_viewers.viewer2D import Viewer2D
from pymodaq.utils.plotting.data_viewers.viewer0D import Viewer0D
import pymodaq.utils.daq_utils as utils
import pymodaq.utils.math_utils as mutils
from pymodaq.utils.data import DataRaw, Axis, DataDistribution, DataWithAxes, DataDim

from pymodaq.utils.plotting.data_viewers.viewer import ViewerBase
from pymodaq.utils.managers.action_manager import ActionManager
from pymodaq.utils.managers.parameter_manager import ParameterManager
from pymodaq.post_treatment.process_Nd_to_scalar import DataNDProcessorFactory
from pymodaq.post_treatment.process_1d_to_scalar import Data1DProcessorFactory


from pymodaq.utils.managers.roi_manager import SimpleRectROI, LinearROI


logger = set_logger(get_module_name(__file__))
math_processorsND = DataNDProcessorFactory()
math_processors1D = Data1DProcessorFactory()


DEBUG_VIEWER = False


class BaseDataDisplayer(QObject):
    data_dim_signal = Signal(str)
    processor_changed = Signal(object)
    distribution: DataDistribution = abstractproperty()

    def __init__(self, viewer0D: Viewer0D, viewer1D: Viewer1D, viewer2D: Viewer2D, navigator1D: Viewer1D,
                 navigator2D: Viewer2D, axes_viewer: AxesViewer):
        super().__init__()
        self._viewer0D = viewer0D
        self._viewer1D = viewer1D
        self._viewer2D = viewer2D
        self._navigator1D = navigator1D
        self._navigator2D = navigator2D
        self._axes_viewer = axes_viewer

        self._data: DataWithAxes = None
        self._nav_limits: tuple = (0, 10, None, None)
        self._signal_at: tuple = (0, 0)

        self._filter_type: str = None
        self._processor = None

    @property
    def data_shape(self):
        return self._data.shape if self._data is not None else None

    def update_filter(self, filter_type: str):
        if filter_type in self._processor.functions:
            self._filter_type = filter_type
            self.update_nav_data(*self._nav_limits)

    def update_processor(self, math_processor):
        self._processor = math_processor
        self.processor_changed.emit(math_processor)

    def update_data(self, data: DataRaw, force_update=False):
        if self._data is None or self._data.shape != data.shape or force_update:
            self._data = data
            self.init(data)
        else:
            self._data.data = data.data[0]

        self.data_dim_signal.emit(self._data.get_data_dimension())

        self.update_viewer_data(*self._signal_at)
        self.update_nav_data(*self._nav_limits)

    @abstractmethod
    def init_rois(self, data: DataRaw):
        """Init crosshairs and ROIs in viewers if needed"""
        ...

    @abstractmethod
    def init(self):
        """init viewers or postprocessing once new data are loaded"""
        ...

    @abstractmethod
    def update_viewer_data(self, **kwargs):
        """ Update the signal display depending on the position of the crosshair in the navigation panels

        """
        ...

    @abstractmethod
    def update_nav_data(self, x, y, width=None, height=None):
        """Display navigator data potentially postprocessed from filters in the signal viewers"""
        ...

    @abstractmethod
    def get_nav_data(self, data: DataWithAxes, x, y, width=None, height=None) -> DataWithAxes:
        """Get filtered data"""
        ...

    def update_nav_data_from_roi(self, roi: Union[SimpleRectROI, LinearROI]):
        if isinstance(roi, LinearROI):
            x, y = roi.getRegion()
            self._nav_limits = (int(x), int(y), None, None)
        elif isinstance(roi, SimpleRectROI):
            x, y = roi.pos().x(), roi.pos().y()
            width, height = roi.size().x(), roi.size().y()
            self._nav_limits = (int(x), int(y), int(width), int(height))
        self.update_nav_data(*self._nav_limits)

    @staticmethod
    def get_out_of_range_limits(x, y, width, height):
        if x < 0:
            width = width + x
            x = 0
        if y < 0:
            height = height + y
            y = 0
        return x, y, width, height

    def update_nav_indexes(self, nav_indexes: List[int]):
        self._data.nav_indexes = nav_indexes
        self.update_data(self._data, force_update=True)

    def update_nav_limits(self, x, y, width=None, height=None):
        self._nav_limits = x, y, width, height


class UniformDataDisplayer(BaseDataDisplayer):
    """Specialized object to filter and plot linearly spaced data in dedicated viewers

    Meant for any navigation axes and up to signal data dimensionality of 2 (images)
    """
    distribution = DataDistribution['uniform']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def init(self, data: DataRaw):
        if len(data.nav_indexes) > 2:
            self._axes_viewer.set_nav_viewers(self._data.get_nav_axes_with_data())
        processor = math_processorsND if len(data.axes_manager.sig_shape) > 1 else math_processors1D
        self.update_processor(processor)

    def init_rois(self, data: DataRaw):
        means = []
        for axis in data.axes_manager.get_nav_axes():
            means.append(axis.mean())
        if len(data.nav_indexes) == 1:
            self._navigator1D.set_crosshair_position(*means)
        elif len(data.nav_indexes) == 2:
            self._navigator2D.set_crosshair_position(*means)

        mins = []
        maxs = []
        for axis in data.axes_manager.get_signal_axes():
            mins.append(axis.min())
            maxs.append(axis.max())
        if len(data.axes_manager.sig_indexes) == 1:
            self._viewer1D.roi.setPos((mins[0], maxs[0]))
        elif len(data.axes_manager.sig_indexes) > 1:
            self._viewer2D.roi.setPos((0, 0))
            self._viewer2D.roi.setSize((len(data.get_axis_from_index(data.axes_manager.sig_indexes[1])),
                                      len(data.get_axis_from_index(data.axes_manager.sig_indexes[0]))))

    def update_viewer_data(self, posx=0, posy=0):
        """ Update the signal display depending on the position of the crosshair in the navigation panels

        Parameters
        ----------
        posx: float
            from the 1D or 2D Navigator crosshair or from one of the navigation axis viewer (in that case
            nav_axis tells from which navigation axis the position comes from)
        posy: float
            from the 2D Navigator crosshair
        """
        self._signal_at = posx, posy
        if self._data is not None:
            try:
                if len(self._data.nav_indexes) == 0:
                    data = self._data

                elif len(self._data.nav_indexes) == 1:
                    nav_axis = self._data.axes_manager.get_nav_axes()[0]
                    if posx < nav_axis.min() or posx > nav_axis.max():
                        return
                    ind_x = nav_axis.find_index(posx)
                    logger.debug(f'Getting the data at nav index {ind_x}')
                    data = self._data.inav[ind_x]

                elif len(self._data.nav_indexes) == 2:
                    nav_x = self._data.axes_manager.get_nav_axes()[1]
                    nav_y = self._data.axes_manager.get_nav_axes()[0]
                    if posx < nav_x.min() or posx > nav_x.max():
                        return
                    if posy < nav_y.min() or posy > nav_y.max():
                        return
                    ind_x = nav_x.find_index(posx)
                    ind_y = nav_y.find_index(posy)
                    logger.debug(f'Getting the data at nav indexes {ind_y} and {ind_x}')
                    data = self._data.inav[ind_y, ind_x]
                else:
                    data = self._data.inav.__getitem__(self._axes_viewer.get_indexes())

                if len(self._data.axes_manager.sig_shape) == 0:  # means 0D data, plot on 0D viewer
                    self._viewer0D.show_data(data)

                elif len(self._data.axes_manager.sig_shape) == 1:  # means 1D data, plot on 1D viewer
                    self._viewer1D.show_data(data)

                elif len(self._data.axes_manager.sig_shape) == 2:  # means 2D data, plot on 2D viewer
                    self._viewer2D.show_data(data)
                    if DEBUG_VIEWER:
                        x, y, width, height = self.get_out_of_range_limits(*self._nav_limits)
                        _data_sig = data.isig[y: y + height, x: x + width]
                        self._debug_viewer_2D.show_data(_data_sig)

            except Exception as e:
                logger.exception(str(e))

    def update_nav_data(self, x, y, width=None, height=None):
        if self._data is not None and self._filter_type is not None and len(self._data.nav_indexes) != 0:
            nav_data = self.get_nav_data(self._data, x, y, width, height)
            if nav_data is not None:
                if len(nav_data.shape) < 2:
                    self._navigator1D.show_data(nav_data)
                elif len(nav_data.shape) == 2:
                    self._navigator2D.show_data(nav_data)
                else:
                    self._axes_viewer.set_nav_viewers(self._data.get_nav_axes_with_data())

    def get_nav_data(self, data: DataRaw, x, y, width=None, height=None):
        try:
            navigator_data = None
            if len(data.axes_manager.sig_shape) == 0:  # signal data is 0D
                navigator_data = data

            elif len(data.axes_manager.sig_shape) == 1:  # signal data is 1D
                _, navigator_data = self._processor.get(self._filter_type).process((x, y), data)

            elif len(data.axes_manager.sig_shape) == 2:  # signal data is 2D
                x, y, width, height = self.get_out_of_range_limits(x, y, width, height)
                if not (width is None or height is None or width < 2 or height < 2):
                    navigator_data = self._processor.get(self._filter_type).process(data.isig[y: y + height, x: x + width])
                else:
                    navigator_data = None
            else:
                navigator_data = None

            return navigator_data

        except Exception as e:
            logger.warning('Could not compute the mathematical function')
        finally:
            return navigator_data


class SpreadDataDisplayer(BaseDataDisplayer):
    """Specialized object to filter and plot non uniformly spaced data in dedicated viewers

    Meant for any navigation axes and up to signal data dimensionality of 2 (images)
    """
    distribution = DataDistribution['spread']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def init(self, data: DataWithAxes):
        processor = math_processorsND if len(data.axes_manager.sig_shape) > 1 else math_processors1D
        self.update_processor(processor)

    def init_rois(self, data: DataRaw):
        pass

    def update_viewer_data(self, posx=0, posy=0):
        """ Update the signal display depending on the position of the crosshair in the navigation panels

        Spread data can be customly represented using:
        if signal data is 0D:
            * A viewer 1D with non-linearly spaced data points (for 1 navigation axis)
            * A viewer 2D with its SpreadImage item (for 2 navigation axis)
            * A double panel: viewer for signal data and viewer 1D for all nav axes as a function of index in the data
        otherwise:
            * A double panel: viewer for signal data and viewer 1D for all nav axes as a function of index in the data
            series

        Parameters
        ----------
        posx: float
            from the 1D or 2D Navigator crosshair or from one of the navigation axis viewer (in that case
            nav_axis tells from which navigation axis the position comes from)
        posy: float
            from the 2D Navigator crosshair
        """
        self._signal_at = posx, posy

        if self._data is not None:
            nav_axes = sorted(self._data.get_nav_axes_with_data(), key=lambda axis: axis.spread_order)
            try:
                if len(nav_axes) == 1:
                    # signal data plotted as a function of nav_axes[0] so get the index corresponding to
                    # the position posx
                    ind_nav = nav_axes[0].find_index(posx)
                    data = self._data.inav[ind_nav]

                elif len(nav_axes) == 2:
                    # signal data plotted as a function of nav_axes[0] and nav_axes[1] so get the common
                    # index corresponding to the position posx and posy
                    ind_nav, x0, y0 = mutils.find_common_index(nav_axes[0].data, nav_axes[1].data, posx, posy)
                    data = self._data.inav[ind_nav]
                else:
                    # navigation plotted as a function of index all nav_axes so get the index corresponding to
                    # the position posx
                    data = self._data.inav[int(posx)]

                if len(self._data.axes_manager.sig_shape) == 0:  # means 0D data, plot on 0D viewer
                    self._viewer0D.show_data(data)

                elif len(self._data.axes_manager.sig_shape) == 1:  # means 1D data, plot on 1D viewer
                    self._viewer1D.show_data(data)

                elif len(self._data.axes_manager.sig_shape) == 2:  # means 2D data, plot on 2D viewer
                    self._viewer2D.show_data(data)
                    if DEBUG_VIEWER:
                        x, y, width, height = self.get_out_of_range_limits(*self._nav_limits)
                        _data_sig = data.isig[y: y + height, x: x + width]
                        self._debug_viewer_2D.show_data(_data_sig)

            except Exception as e:
                logger.exception(str(e))

    def update_nav_data(self, x, y, width=None, height=None):
        if self._data is not None and self._filter_type is not None and len(self._data.nav_indexes) != 0:
            nav_data = self.get_nav_data(self._data, x, y, width, height)
            nav_axes = nav_data.get_nav_axes()
            if nav_data is not None:
                if len(nav_axes) < 2:
                    self._navigator1D.show_data(nav_data)
                elif len(nav_axes) == 2:
                    self._navigator2D.show_data(nav_data)
                else:
                    self._axes_viewer.set_nav_viewers(self._data.get_nav_axes_with_data())

    def get_nav_data(self, data: DataRaw, x, y, width=None, height=None):
        try:
            navigator_data = None
            if len(data.axes_manager.sig_shape) == 0:  # signal data is 0D
                navigator_data = data

            elif len(data.axes_manager.sig_shape) == 1:  # signal data is 1D
                _, navigator_data = self._processor.get(self._filter_type).process((x, y), data)

            elif len(data.axes_manager.sig_shape) == 2:  # signal data is 2D
                x, y, width, height = self.get_out_of_range_limits(x, y, width, height)
                if not (width is None or height is None or width < 2 or height < 2):
                    navigator_data = self._processor.get(self._filter_type).process(data.isig[y: y + height, x: x + width])
                else:
                    navigator_data = None
            else:
                navigator_data = None

            return navigator_data

        except Exception as e:
            logger.warning('Could not compute the mathematical function')
        finally:
            return navigator_data

    def get_nav_position(self, posx=0, posy=None):
        """
        crosshair position from the "spread" data viewer. Should return scan index where the scan was closest to posx,
        posy coordinates
        Parameters
        ----------
        posx
        posy

        See Also
        --------
        update_viewer_data
        """
        # todo adapt to new layout

        nav_axes = self.get_selected_axes()
        if len(nav_axes) != 0:
            if 'datas' in nav_axes[0]:
                datas = nav_axes[0]['datas']
                xaxis = datas[0]
                if len(datas) > 1:
                    yaxis = datas[1]
                    ind_scan = utils.find_common_index(xaxis, yaxis, posx, posy)
                else:
                    ind_scan = mutils.find_index(xaxis, posx)[0]

                self.navigator1D.ui.crosshair.set_crosshair_position(ind_scan[0])


class ViewerND(ParameterManager, ActionManager, ViewerBase):
    params = [
        {'title': 'Set data spread 0D', 'name': 'set_data_spread0D', 'type': 'action', 'visible': False},
        {'title': 'Set data spread 1D', 'name': 'set_data_spread1D', 'type': 'action', 'visible': False},
        {'title': 'Set data spread 2D', 'name': 'set_data_spread2D', 'type': 'action', 'visible': False},
        {'title': 'Set data 4D', 'name': 'set_data_4D', 'type': 'action', 'visible': False},
        {'title': 'Set data 3D', 'name': 'set_data_3D', 'type': 'action', 'visible': False},
        {'title': 'Set data 2D', 'name': 'set_data_2D', 'type': 'action', 'visible': False},
        {'title': 'Set data 1D', 'name': 'set_data_1D', 'type': 'action', 'visible': False},
        {'title': 'Signal shape', 'name': 'data_shape_settings', 'type': 'group', 'children': [
            {'title': 'Initial Data shape:', 'name': 'data_shape_init', 'type': 'str', 'value': "",
             'readonly': True},
            {'title': 'Axes shape:', 'name': 'nav_axes_shapes', 'type': 'group', 'children': [],
             'readonly': True},
            {'title': 'Data shape:', 'name': 'data_shape', 'type': 'str', 'value': "", 'readonly': True},
            {'title': 'Navigator axes:', 'name': 'navigator_axes', 'type': 'itemselect'},
            {'title': 'Set Nav axes:', 'name': 'set_nav_axes', 'type': 'action', 'visible': True},
        ]},
    ]

    def __init__(self, parent_widget: QtWidgets.QWidget, title=''):
        ViewerBase.__init__(self, parent_widget, title=title)
        ActionManager.__init__(self, toolbar=QtWidgets.QToolBar())
        ParameterManager.__init__(self)

        self._area = None
        self._data = None

        self.viewer0D: Viewer0D = None
        self.viewer1D: Viewer1D = None
        self.viewer2D: Viewer2D = None
        self.navigator1D: Viewer1D = None
        self.navigator2D: Viewer2D = None
        self.axes_viewer: AxesViewer = None

        self.setup_widgets()

        self.data_displayer: BaseDataDisplayer = None

        self.setup_actions()

        self.connect_things()

        self.prepare_ui()

    def update_data_displayer(self, distribution: DataDistribution):
        if distribution.name == 'uniform':
            self.data_displayer = UniformDataDisplayer(self.viewer0D, self.viewer1D, self.viewer2D,
                                                       self.navigator1D, self.navigator2D,
                                                       self.axes_viewer)
        else:
            self.data_displayer = SpreadDataDisplayer(self.viewer0D, self.viewer1D, self.viewer2D,
                                                       self.navigator1D, self.navigator2D,
                                                       self.axes_viewer)

        self.navigator1D.crosshair.crosshair_dragged.connect(self.data_displayer.update_viewer_data)
        self.navigator2D.crosshair_dragged.connect(self.data_displayer.update_viewer_data)
        self.axes_viewer.navigation_changed.connect(self.data_displayer.update_viewer_data)
        self.data_displayer.data_dim_signal.connect(self.update_data_dim)

        self.viewer1D.roi.sigRegionChanged.connect(self.data_displayer.update_nav_data_from_roi)
        self.viewer2D.roi.sigRegionChanged.connect(self.data_displayer.update_nav_data_from_roi)

        self.get_action('filters').currentTextChanged.connect(self.data_displayer.update_filter)
        self.data_displayer.processor_changed.connect(self.update_filters)

    def _show_data(self, data: DataRaw, **kwargs):
        force_update = False
        self.settings.child('data_shape_settings', 'data_shape_init').setValue(str(data.shape))
        self.settings.child('data_shape_settings', 'navigator_axes').setValue(
            dict(all_items=[str(ax.index) for ax in data.axes],
                 selected=[str(ax.index) for ax in data.get_nav_axes()]))

        if self._data is None or self._data.dim != data.dim or self._data.nav_indexes != data.nav_indexes:
            force_update = True
        if 'force_update' in kwargs:
            force_update = kwargs['force_update']

        if self.data_displayer is None or data.distribution != self.data_displayer.distribution:
            self.update_data_displayer(data.distribution)

        self.data_displayer.update_data(data, force_update=force_update)
        self._data = data

        if force_update:
            self.update_widget_visibility(data)
            self.data_displayer.init_rois(data)
        self.data_to_export_signal.emit(self.data_to_export)

    def set_data_test(self, data_shape='3D'):
        if 'spread' in data_shape:
            data_tri = np.load('../../../resources/triangulation_data.npy')
            axes = [Axis(data=data_tri[:, 0], index=0, label='x_axis', units='xunits', spread_order=0),
                    Axis(data=data_tri[:, 1], index=0, label='y_axis', units='yunits', spread_order=1)]

            if data_shape == 'spread0D':
                data = data_tri[:, 2]
            elif data_shape == 'spread1D':
                x = np.linspace(-50, 50, 100)
                data = np.zeros((data_tri.shape[0], len(x)))
                for ind in range(data_tri.shape[0]):
                    data[ind, :] = data_tri[ind, 2] * mutils.gauss1D(x, ind - 50, 20)
                axes.append(Axis(data=x, index=1, label='sig_axis'))
            elif data_shape == 'spread2D':
                x = np.linspace(-50, 50, 100)
                y = np.linspace(-50, 50, 75)
                data = np.zeros((data_tri.shape[0], len(x), len(y)))
                for ind in range(data_tri.shape[0]):
                    data[ind, :] = data_tri[ind, 2] * mutils.gauss2D(x, ind - 50, 20,
                                                                     y, ind-50, 10)
                axes.append(Axis(data=x, index=1, label='sig_axis0'))
                axes.append(Axis(data=y, index=2, label='sig_axis1'))
            dataraw = DataRaw('NDdata', distribution='spread', dim='DataND',
                              data=[data], nav_indexes=(0, ),
                              axes=axes)
        else:
            x = mutils.linspace_step(-10, 10, 0.2)
            y = mutils.linspace_step(-30, 30, 2)
            t = mutils.linspace_step(-200, 200, 2)
            z = mutils.linspace_step(-50, 50, 0.5)
            data = np.zeros((len(y), len(x), len(t), len(z)))
            amp = mutils.gauss2D(x, 0, 5, y, 0, 4) + 0.1 * np.random.rand(len(y), len(x))
            amp = np.ones((len(y), len(x), len(t), len(z)))
            for indx in range(len(x)):
                for indy in range(len(y)):
                    data[indy, indx, :, :] = amp[indy, indx] * (
                        mutils.gauss2D(z, -50 + indx * 1, 20,
                                       t, 0 + 2 * indy, 30)
                        + np.random.rand(len(t), len(z)) / 10)

            if data_shape == '4D':
                dataraw = DataRaw('NDdata', data=data, dim='DataND', nav_indexes=[0, 1],
                                  axes=[Axis(data=y, index=0, label='y_axis', units='yunits'),
                                        Axis(data=x, index=1, label='x_axis', units='xunits'),
                                        Axis(data=t, index=2, label='t_axis', units='tunits'),
                                        Axis(data=z, index=3, label='z_axis', units='zunits')])
            elif data_shape == '3D':
                data = [np.sum(data, axis=2)]
                dataraw = DataRaw('NDdata', data=data, dim='DataND', nav_indexes=[0, 1],
                                  axes=[Axis(data=y, index=0, label='y_axis', units='yunits'),
                                        Axis(data=x, index=1, label='x_axis', units='xunits'),
                                        Axis(data=t, index=2, label='t_axis', units='tunits')])
            elif data_shape == '2D':
                data = [np.sum(data, axis=(2, 3))]
                dataraw = DataRaw('NDdata', data=data, dim='DataND', nav_indexes=[0, 1],
                                  axes=[Axis(data=y, index=0, label='y_axis', units='yunits'),
                                        Axis(data=x, index=1, label='x_axis', units='xunits')])
            elif data_shape == '1D':
                data = [np.sum(data, axis=(0, 1, 2))]
                dataraw = DataRaw('NDdata', data=data, dim='DataND', nav_indexes=[],
                                  axes=[Axis(data=z, index=0, label='z_axis', units='zunits')])
        self._show_data(dataraw)

    def update_widget_visibility(self, data: DataRaw = None):
        if data is None:
            data = self._data
        self.viewer0D.setVisible(len(data.shape) - len(data.nav_indexes) == 0)
        self.viewer1D.setVisible(len(data.shape) - len(data.nav_indexes) == 1)
        self.viewer2D.setVisible(len(data.shape) - len(data.nav_indexes) == 2)
        self.viewer1D.roi.setVisible(len(data.nav_indexes) != 0)
        self.viewer2D.roi.setVisible(len(data.nav_indexes) != 0)
        self._dock_navigation.setVisible(len(data.nav_indexes) != 0)
        nav_axes = data.get_nav_axes()
        self.navigator1D.setVisible(len(nav_axes) == 1 or (len(nav_axes) > 2 and data.distribution.name == 'spread'))
        self.navigator2D.setVisible(len(nav_axes) == 2)
        self.axes_viewer.setVisible(len(data.nav_indexes) > 2 and data.distribution.name == 'uniform')

    def update_filters(self, processor):
        self.get_action('filters').clear()
        self.get_action('filters').addItems(processor.functions)

    def show_settings(self, show: bool = True):
        if show:
            self.settings_tree.show()
        else:
            self.settings_tree.hide()

    def prepare_ui(self):
        self.navigator1D.setVisible(False)
        self.viewer2D.setVisible(False)
        self.navigator1D.setVisible(False)
        self.viewer2D.setVisible(False)

    def setup_actions(self):
        self.add_action('setaxes', icon_name='cartesian', checkable=True, tip='Change navigation/signal axes')
        self.add_widget('filters', QtWidgets.QComboBox, tip='Filter type to apply to signal data')

    def reshape_data(self):
        _nav_indexes = [int(index) for index in
                        self.settings.child('data_shape_settings', 'navigator_axes').value()['selected']]
        self.update_widget_visibility()
        self.data_displayer.update_nav_indexes(_nav_indexes)

    def connect_things(self):
        self.settings.child('set_data_1D').sigActivated.connect(lambda: self.set_data_test('1D'))
        self.settings.child('set_data_2D').sigActivated.connect(lambda: self.set_data_test('2D'))
        self.settings.child('set_data_3D').sigActivated.connect(lambda: self.set_data_test('3D'))
        self.settings.child('set_data_4D').sigActivated.connect(lambda: self.set_data_test('4D'))
        self.settings.child('set_data_spread0D').sigActivated.connect(lambda: self.set_data_test('spread0D'))
        self.settings.child('set_data_spread1D').sigActivated.connect(lambda: self.set_data_test('spread1D'))
        self.settings.child('set_data_spread2D').sigActivated.connect(lambda: self.set_data_test('spread2D'))
        self.settings.child('data_shape_settings', 'set_nav_axes').sigActivated.connect(self.reshape_data)

        self.navigator1D.get_action('crosshair').trigger()
        self.connect_action('setaxes', self.show_settings)

    def setup_widgets(self):
        self.parent.setLayout(QtWidgets.QVBoxLayout())
        self.parent.layout().addWidget(self.toolbar)

        self._area = DockArea()
        self.parent.layout().addWidget(self._area)

        viewer0D_widget = QtWidgets.QWidget()
        self.viewer0D = Viewer0D(viewer0D_widget)

        viewer1D_widget = QtWidgets.QWidget()
        self.viewer1D = Viewer1D(viewer1D_widget)
        self.viewer1D.roi = LinearROI()
        self.viewer1D.view.plotitem.addItem(self.viewer1D.roi)

        viewer2D_widget = QtWidgets.QWidget()
        self.viewer2D = Viewer2D(viewer2D_widget)
        self.viewer2D.roi = SimpleRectROI(centered=True)
        self.viewer2D.view.plotitem.addItem(self.viewer2D.roi)
        
        self.viewer2D.set_action_visible('flip_ud', False)
        self.viewer2D.set_action_visible('flip_lr', False)
        self.viewer2D.set_action_visible('rotate', False)
        self.viewer2D.get_action('autolevels').trigger()

        self._dock_signal = Dock('Signal')
        self._dock_signal.addWidget(viewer0D_widget)
        self._dock_signal.addWidget(viewer1D_widget)
        self._dock_signal.addWidget(viewer2D_widget)

        navigator1D_widget = QtWidgets.QWidget()
        self.navigator1D = Viewer1D(navigator1D_widget)
        navigator2D_widget = QtWidgets.QWidget()
        self.navigator2D = Viewer2D(navigator2D_widget)
        self.navigator2D.get_action('autolevels').trigger()
        self.navigator2D.get_action('crosshair').trigger()

        nav_axes_widget = QtWidgets.QWidget()
        nav_axes_widget.setVisible(False)
        self.axes_viewer = AxesViewer(nav_axes_widget)

        self._dock_navigation = Dock('Navigation')
        self._dock_navigation.addWidget(navigator1D_widget)
        self._dock_navigation.addWidget(navigator2D_widget)
        self._dock_navigation.addWidget(nav_axes_widget)

        self._area.addDock(self._dock_navigation)
        self._area.addDock(self._dock_signal, 'right', self._dock_navigation)

    def update_data_dim(self, dim: str):
        self.settings.child('data_shape_settings', 'data_shape').setValue(dim)

    def setup_spread_UI(self):
        #todo adapt to new layout
        self.ui.spread_widget = QtWidgets.QWidget()
        self.ui.spread_widget.setLayout(QtWidgets.QVBoxLayout())
        widget1D = QtWidgets.QWidget()
        widget2D = QtWidgets.QWidget()
        self.ui.spread_viewer_1D = Viewer1D(widget1D)
        self.ui.spread_viewer_2D = Viewer2D(widget2D)
        self.ui.spread_widget.layout().addWidget(widget1D)
        self.ui.spread_widget.layout().addWidget(widget2D)

        self.ui.spread_viewer_1D.ui.crosshair.crosshair_dragged.connect(self.get_nav_position)
        self.ui.spread_viewer_1D.ui.crosshair_pb.trigger()
        self.ui.spread_viewer_2D.get_action('autolevels').trigger()

        self.ui.spread_viewer_2D.crosshair_dragged.connect(self.get_nav_position)
        self.ui.spread_viewer_2D.get_action('crosshair').trigger()

        self.ui.spread_widget.show()
        self.ui.spread_widget.setVisible(False)




def main():
    app = QtWidgets.QApplication(sys.argv)
    widget = QtWidgets.QWidget()
    prog = ViewerND(widget)
    for child in prog.settings.children():
        if 'set_data_' in child.name():
            child.show(True)
    prog.show_settings()

    widget.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

