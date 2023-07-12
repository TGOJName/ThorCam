#####################################################################
#                                                                   #
# /labscript_devices/ThorCam/blacs_workers.py             #
#                                                                   #
# Copyright 2019, Monash University and contributors                #
#                                                                   #
# This file is part of labscript_devices, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

# Original imaqdx_camera server by dt, with modifications by rpanderson and cbillington.
# Refactored as a BLACS worker by cbillington
# Original PyCapture2_camera_server by dsbarker
# Ported to BLACS worker by dihm

import numpy as np
from labscript_utils import dedent
from enum import IntEnum
import os

from labscript_devices.IMAQdxCamera.blacs_workers import IMAQdxCameraWorker

# Don't import API yet so as not to throw an error, allow worker to run as a dummy
# device, or for subclasses to import this module to inherit classes without requiring API
TLCameraSDK = None
absolute_path_to_dlls = ""

operation_mode_dict = {'SOFTWARE_TRIGGERED':0,'HARDWARE_TRIGGERED':1,'BULB':2}

class Thorlab_Camera(object):
    """The backend hardware interface class for the ThorCam.
    
    This class handles all of the API/hardware implementation details for the
    corresponding labscript device. It is used by the BLACS worker to send
    appropriate API commands to the camera for the standard BLACS camera operations
    (i.e. transition_to_buffered, get_attributes, snap, etc).
    
    Attributes:
        camera (PyCapture2.Camera): Handle to connected camera.
        get_props (list): This list sets which values of each property object 
            are returned when queried by :obj:`get_attribute`.
        pixel_formats (IntEnum): An IntEnum object that is automatically 
            populated with the supported pixel types of the connected camera.
        width (int): Width of images for most recent acquisition. 
            Used by :obj:`_decode_image_data` to format images correctly.
        height (int): Height of images for most recent acquisition.
            Used by :obj:`_decode_image_data` to format images correctly.
        pixelFormat (str): Pixel format name for most recent acquisition.
            Used by :obj:`_decode_image_data` to format images correctly.
        _abort_acquisition (bool): Abort flag that is polled during buffered
            acquisitions.
    """
    def __init__(self, serial_number):
        """Initialize FlyCapture2 API camera.
        
        Searches all cameras reachable by the host using the provided serial
        number. Fails with API error if camera not found.
        
        This function also does a significant amount of default configuration.
        
        * It defaults the grab timeout to 1 s
        * Ensures use of the API's HighPerformanceRetrieveBuffer
        * Ensures the camera is in Format 7, Mode 0 with full frame readout and MONO8 pixels
        * If using a GigE camera, automatically maximizes the packet size and warns if Jumbo packets are not enabled on the NIC
        
        Args:
            serial_number (int): serial number of camera to connect to
        """
        os.environ['PATH']=r'C:\Windows\System32'+os.pathsep+os.environ['PATH']
        # Python 3.8 introduces a new method to specify dll directory
        os.add_dll_directory(r'C:\Windows\System32')

        global TLCameraSDK
        from labscript_devices.ThorCam.source.tl_camera import TLCameraSDK
        
        self.thorsdk = TLCameraSDK()
        available_cameras = self.thorsdk.discover_available_cameras()
        if len(available_cameras) < 1:
            raise ValueError("no cameras detected")
        print('Connecting to SN:%d ...'%serial_number)

        self.camera = self.thorsdk.open_camera(str(serial_number))
        
        # set which values of properties to return
        self.props = {}
        
        if self.camera.is_armed:
            self.camera.disarm()

        self._abort_acquisition = False
        self.exception_on_failed_shot = True

    def get_attributes(self):
        self.props['OperationMode'] = self.camera.operation_mode
        self.props['Gain'] = self.camera.gain
        self.props['ExposureTime'] = self.camera.exposure_time_us
        self.props['BLackLevel'] = self.camera.black_level
        self.props['Width'] = self.camera.image_width_pixels
        self.props['Height'] = self.camera.image_height_pixels
        return self.props

    def set_attributes(self, attr_dict):
        """Sets all attribues in attr_dict.
        
        FlyCapture does not control all settings through same interface,
        so we must do them separately.
        Interfaces are: <Standard PROPERTY_TYPE>, TriggerMode, ImageMode
            
        Args:
            attr_dict (dict): dictionary of property dictionaries to set for the camera.
                These property dictionaries assume a specific structure, outlined in
                :obj:`set_attribute`, :obj:`set_trigger_mode` and , :obj:`set_image_mode`
                methods.
        """
        if self.camera.is_armed:
            self.camera.disarm()
        for prop, vals in attr_dict.items():
                
            if prop == 'OperationMode':
                self.set_operation_mode(vals)
            elif prop == 'Gain':
                self.set_gain(vals)
            elif prop == 'ExposureTime':
                self.set_exposure(vals)
            elif prop == 'BLackLevel':
                self.set_blackLevel(vals)
            
    def set_operation_mode(self,operationMode):
        """Configures ROI and image control via Format 7, Mode 0 interface.
        
        Args:
            image_settings (dict): dictionary of image settings. Allowed keys:
                
                * 'pixelFormat': valid pixel format string, i.e. 'MONO8'
                * 'offsetX': int
                * 'offsetY': int
                * 'width': int
                * 'height': int
        """
        self.camera.operation_mode=operation_mode_dict[operationMode]

    def set_gain(self, gain):
        if gain > 48 or gain < 0:
            raise ValueError("Gain must be between 0 and 48")
        else:
            self.camera.gain=gain

    def set_exposure(self,exposureTime):
        self.camera.exposure_time_us=exposureTime
    
    def set_blackLevel(self, blackLevel):
        blackLevel = int(blackLevel)
        if blackLevel > 511 or blackLevel < 0:
            raise ValueError("Gain must be between 0 and 48")
        else:
            self.camera.black_level=blackLevel  


    # def set_attribute(self, name, values):
    #     """Set the values of the attribute of the given name using the provided
    #     dictionary values. 
        
    #     Generally, absControl should be used to configure settings. Note that
    #     invalid settings tend to coerce instead of presenting an error.
        
    #     Args:
    #         name (str): 
    #         values (dict): Dictionary of settings for the property. Allowed keys are:
                
    #             * 'onOff': bool
    #             * 'autoManualMode': bool
    #             * 'absControl': bool
    #             * 'absValue': float
    #             * 'valueA': int
    #             * 'valueB': int
    #             * 'onePush': bool
    #     """
    #     try:
    #         prop = self.camera.getProperty(getattr(PyCapture2.PROPERTY_TYPE,name))
            
    #         for key, val in values.items():
    #             setattr(prop,key,val)
    #         self.camera.setProperty(prop)
    #     except Exception as e:
    #         # Add some info to the exception:
    #         msg = f"failed to set attribute {name} to {values}"
    #         raise Exception(msg) from e
        

    def snap(self):
        """Acquire a single image and return it
        
        Returns:
            numpy.array: Acquired image
        """
        if self.camera.is_armed:
            self.camera.disarm()
        self.configure_acquisition(continuous=False,bufferCount=1)
        image = self.grab()
        self.stop_acquisition()
        return image

    def configure_acquisition(self, continuous=True, bufferCount=2):
        """Configure acquisition buffer count and grab mode.
        
        This method also saves image width, heigh, and pixelFormat to class
        attributes for returned image formatting.
        
        Args:
            continuous (:obj:`bool`, optional): If True, camera will continuously
                acquire and only keep most recent frames in the buffer. If False,
                all acquired frames are kept and error occurs if buffer is exceeded.
                Default is True.
            bufferCount (:obj:`int`, optional): Number of memory buffers to use 
                in the acquistion. Default is 10.
        """
        print('nframe'+str(self.camera.frames_per_trigger_zero_for_unlimited))
        if continuous:
            self.camera.frames_per_trigger_zero_for_unlimited = 0
        else:
            self.camera.frames_per_trigger_zero_for_unlimited = 1
            
        self.set_operation_mode('SOFTWARE_TRIGGERED')
        self.camera.arm(2)
            
    def grab(self):
        """Grab and return single image during pre-configured acquisition.
        
        Returns:
            numpy.array: Returns formatted image
        """
        
        self.camera.issue_software_trigger()
        img =None
        while not img:
            img = self.camera.get_pending_frame_or_null()

        print(img.image_buffer)
        #result.ReleaseBuffer(), exists in documentation, not PyCapture2
        return img.image_buffer

    def grab_multiple(self, n_images, images):
        """Grab n_images into images array during buffered acquistion.
        
        Grab method involves a continuous loop with fast timeout in order to
        poll :obj:`_abort_acquisition` for a signal to abort.
        
        Args:
            n_images (int): Number of images to acquire. Should be same number
                as the bufferCount in :obj:`configure_acquisition`.
            images (list): List that images will be saved to as they are acquired
        """
        print(f"Attempting to grab {n_images} images.")
        for i in range(n_images):
            while True:
                if self._abort_acquisition:
                    print("Abort during acquisition.")
                    self._abort_acquisition = False
                    return
                try:
                    images.append(self.grab())
                    print(f"Got image {i+1} of {n_images}.")
                    break
                except:
                    print('.', end='')
                    continue
        print(f"Got {len(images)} of {n_images} images.")


    def stop_acquisition(self):
        """Tells camera to stop current acquistion."""
        self.camera.disarm()

    def abort_acquisition(self):
        """Sets :obj:`_abort_acquisition` flag to break buffered acquisition loop."""
        self._abort_acquisition = True

    def close(self):
        """Closes :obj:`camera` handle to the camera."""
        self.camera.dispose()
        self.thorsdk.dispose()


class ThorCamWorker(IMAQdxCameraWorker):
    """FlyCapture2 API Camera Worker. 
    
    Inherits from obj:`IMAQdxCameraWorker`. Defines :obj:`interface_class` and overloads
    :obj:`get_attributes_as_dict` to use ThorCam.get_attributes() method."""
    interface_class = Thorlab_Camera

    def get_attributes_as_dict(self, visibility_level):
        """Return a dict of the attributes of the camera for the given visibility
        level
        
        Args:
            visibility_level (str): Normally configures level of attribute detail
                to return. Is not used by Thorlab_Camera.
        """
        if self.mock:
            return IMAQdxCameraWorker.get_attributes_as_dict(self,visibility_level)
        else:
            return self.camera.get_attributes()


