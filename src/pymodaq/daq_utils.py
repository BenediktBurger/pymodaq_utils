# -*- coding: utf-8 -*-
"""
Created the 27/10/2022

@author: Sebastien Weber
"""
import sys
from importlib import import_module

from pymodaq.utils.messenger import deprecation_msg

deprecation_msg('Importing from pymodaq.daq_utils is deprecated, use pymodaq.utils.'
                'It will cause an error in version 4.1.0', 3)

sys.modules['pymodaq.daq_utils'] = import_module('.utils', 'pymodaq')
sys.modules['pymodaq.daq_utils.abstract.logger'] = import_module('.abstract.logger', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.array_manipulation'] = import_module('.array_manipulation', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.calibration_camera'] = import_module('.calibration_camera', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.chrono_timer'] = import_module('.chrono_timer', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.config'] = import_module('.config', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.conftests'] = import_module('.conftests', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.daq_enums'] = import_module('.daq_enums', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.daq_utils'] = import_module('.daq_utils', 'pymodaq.utils')
try:
    import sqlalchemy
    sys.modules['pymodaq.daq_utils.db.db_logger.db_logger'] = import_module('.db.db_logger.db_logger', 'pymodaq.utils')
    sys.modules['pymodaq.daq_utils.db.db_logger.db_logger_models'] = import_module('.db.db_logger.db_logger_models', 'pymodaq.utils')
except ModuleNotFoundError:
    pass
sys.modules['pymodaq.daq_utils.exceptions'] = import_module('.exceptions', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.custom_app'] = import_module('.gui_utils.custom_app', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.dock'] = import_module('.gui_utils.dock', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.file_io'] = import_module('.gui_utils.file_io', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.layout'] = import_module('.gui_utils.layout', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.list_picker'] = import_module('.gui_utils.list_picker', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.utils'] = import_module('.gui_utils.utils', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.widgets.label'] = import_module('.gui_utils.widgets.label', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.widgets.lcd'] = import_module('.gui_utils.widgets.lcd', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.widgets.push'] = import_module('.gui_utils.widgets.push', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.widgets.qled'] = import_module('.gui_utils.widgets.qled', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.widgets.spinbox'] = import_module('.gui_utils.widgets.spinbox', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.gui_utils.widgets.table'] = import_module('.gui_utils.widgets.table', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.h5modules'] = import_module('.h5modules', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.managers.action_manager'] = import_module('.managers.action_manager', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.managers.batchscan_manager'] = import_module('.managers.batchscan_manager', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.managers.modules_manager'] = import_module('.managers.modules_manager', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.managers.overshoot_manager'] = import_module('.managers.overshoot_manager', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.managers.parameter_manager'] = import_module('.managers.parameter_manager', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.managers.preset_manager'] = import_module('.managers.preset_manager', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.managers.preset_manager_utils'] = import_module('.managers.preset_manager_utils', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.managers.remote_manager'] = import_module('.managers.remote_manager', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.managers.roi_manager'] = import_module('.managers.roi_manager', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.math_utils'] = import_module('.math_utils', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.messenger'] = import_module('.messenger', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.ioxml'] = import_module('.parameter.ioxml', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.bool'] = import_module('.parameter.pymodaq_ptypes.bool', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.date'] = import_module('.parameter.pymodaq_ptypes.date', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.filedir'] = import_module('.parameter.pymodaq_ptypes.filedir', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.itemselect'] = import_module('.parameter.pymodaq_ptypes.itemselect', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.led'] = import_module('.parameter.pymodaq_ptypes.led', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.list'] = import_module('.parameter.pymodaq_ptypes.list', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.numeric'] = import_module('.parameter.pymodaq_ptypes.numeric', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.pixmap'] = import_module('.parameter.pymodaq_ptypes.pixmap', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.slide'] = import_module('.parameter.pymodaq_ptypes.slide', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.table'] = import_module('.parameter.pymodaq_ptypes.table', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.tableview'] = import_module('.parameter.pymodaq_ptypes.tableview', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.pymodaq_ptypes.text'] = import_module('.parameter.pymodaq_ptypes.text', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.parameter.utils'] = import_module('.parameter.utils', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.data_viewers.viewer0D'] = import_module('.plotting.data_viewers.viewer0D', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.data_viewers.viewer0D_GUI'] = import_module('.plotting.data_viewers.viewer0D_GUI', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.data_viewers.viewer1D'] = import_module('.plotting.data_viewers.viewer1D', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.data_viewers.viewer1Dbasic'] = import_module('.plotting.data_viewers.viewer1Dbasic', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.data_viewers.viewer2D'] = import_module('.plotting.data_viewers.viewer2D', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.data_viewers.viewer2D_basic'] = import_module('.plotting.data_viewers.viewer2D_basic', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.data_viewers.viewerbase'] = import_module('.plotting.data_viewers.viewerbase', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.data_viewers.viewerND'] = import_module('.plotting.data_viewers.viewerND', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.image_viewer'] = import_module('.plotting.image_viewer', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.items.axis_scaled'] = import_module('.plotting.items.axis_scaled', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.items.crosshair'] = import_module('.plotting.items.crosshair', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.items.image'] = import_module('.plotting.items.image', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.navigator'] = import_module('.plotting.navigator', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.scan_selector'] = import_module('.plotting.scan_selector', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.utils.filter'] = import_module('.plotting.utils.filter', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.utils.plot_utils'] = import_module('.plotting.utils.plot_utils', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.plotting.utils.signalND'] = import_module('.plotting.utils.signalND', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.qvariant'] = import_module('.qvariant', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.scanner'] = import_module('.scanner', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.tcp_server_client'] = import_module('.tcp_server_client', 'pymodaq.utils')
sys.modules['pymodaq.daq_utils.tree_layout.tree_layout_main'] = import_module('.tree_layout.tree_layout_main', 'pymodaq.utils')
