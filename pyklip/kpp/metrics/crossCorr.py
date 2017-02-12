__author__ = 'JB'
import os
import astropy.io.fits as pyfits
from glob import glob
import multiprocessing as mp
import numpy as np
from scipy.signal import correlate2d

from pyklip.kpp.utils.kppSuperClass import KPPSuperClass
from pyklip.kpp.stat.stat_utils import *
from pyklip.kpp.utils.GOI import *
import pyklip.kpp.utils.mathfunc as kppmath

class CrossCorr(KPPSuperClass):
    """
    Cross correlate data.
    """
    def __init__(self,read_func,filename,
                 inputDir = None,
                 outputDir = None,
                 folderName = None,
                 mute=None,
                 N_threads=None,
                 label = None,
                 overwrite = False,
                 kernel_type = None,
                 kernel_para = None,
                 collapse = None,
                 weights = None,
                 nans2zero = None):
        """
        Define the general parameters of the cross correlation:
            - cross correlation template
            - weighted mean of the input data (if collapsing a cube)

        Args:
            read_func: lambda function treturning a instrument object where the only input should be a list of filenames
                    to read.
                    For e.g.:
                    read_func = lambda filenames:GPI.GPIData(filenames,recalc_centers=False,recalc_wvs=False,highpass=False)
            filename: Filename of the file to process.
                        It should be the complete path unless inputDir is used in initialize().
                        It can include wild characters. The files will be reduced as given by glob.glob().
            folderName: foldername used in the definition of self.outputDir (where files shoudl be saved) in initialize().
                        folderName could be the name of the spectrum used for the reduction for e.g.
                        Default folder name is "default_out".
                        Convention is self.outputDir = #outputDir#/kpop_#labe#/#folderName#/
            mute: If True prevent printed log outputs.
            N_threads: Number of threads to be used for the metrics and the probability calculations.
                        If None use mp.cpu_count().
                        If -1 do it sequentially.
                        Note that it is not used for this super class.
            label: label used in the definition of self.outputDir (where files shoudl be saved) in initialize().
                   Default is "default".
                   Convention is self.outputDir = #outputDir#/kpop_#labe#/#folderName#/
            overwrite: Boolean indicating whether or not files should be overwritten if they exist.
                       See check_existence().
            kernel_type: String defining type of model to be used for the cross correlation:
                    - "hat": Define the kernel as a simple aperture photometry with radius kernel_para.
                            Default radius is 1.5 pixels.
                    - "Gaussian": define the kernel as a symmetric 2D gaussian with width (ie standard deviation) equal
                            to kernel_para. Default value of the width is 1.25.
                    - If kernel_type is a np.ndarray then kernel_type is the user defined template.
            kernel_para: Define the width of the Kernel depending on kernel_type. See kernel_type.
            collapse: If true and input is 3D then it will collapse the final map. See weights for weighted collapse.
            weights: If not None and collapse is True then a weighted mean is performed using the weights.
            nans2zero: If True, replace all nans values with zeros.


        Return: instance of CrossCorr.
        """
        # allocate super class
        super(CrossCorr, self).__init__(read_func,filename,
                                     inputDir = inputDir,
                                     outputDir = outputDir,
                                     folderName = folderName,
                                     mute=mute,
                                     N_threads=N_threads,
                                     label=label,
                                     overwrite = overwrite)


        self.kernel_type = kernel_type
        # The default value is defined later
        self.kernel_para = kernel_para

        if collapse is None:
            self.collapse = False
        else:
            self.collapse = collapse
        self.weights = weights
        if nans2zero is None:
            self.nans2zero = True
        else:
            self.nans2zero = nans2zero

    def initialize(self,inputDir = None,
                         outputDir = None,
                         folderName = None,
                         compact_date = None,
                         label = None):
        """
        Read the file using read_func (see the class  __init__ function) and define the cross correlation kernel
        according to kernel_type.

        Can be called several time to process all the files matching the filename.

        Also define the output filename (if it were to be saved) such that check_existence() can be used.

        Args:
            inputDir: If defined it allows filename to not include the whole path and just the filename.
                            Files will be read from inputDir.
                            If inputDir is None then filename is assumed to have the absolute path.
            outputDir: Directory where to create the folder containing the outputs.
                    A kpop folder will be created to save the data. Convention is:
                    self.outputDir = outputDir+os.path.sep+"kpop_"+label+os.path.sep+folderName
            folderName: Name of the folder containing the outputs. It will be located in outputDir+os.path.sep+"kpop_"+label
                            Default folder name is "default_out".
                            A nice convention is to have one folder per spectral template.
            label: Define the suffix of the kpop output folder when it is not defined. cf outputDir. Default is "default".
            read: If true (default) read the fits file according to inputDir and filename otherwise only define self.outputDir.

        Return: True if all the files matching the filename (with wildcards) have been processed. False otherwise.
        """
        if not self.mute:
            print("~~ INITializing "+self.__class__.__name__+" ~~")
        # The super class already read the fits file
        init_out = super(CrossCorr, self).initialize(inputDir = inputDir,
                                         outputDir = outputDir,
                                         folderName = folderName,
                                         label=label)

        try:
            self.folderName = self.exthdr["KPPFOLDN"]+os.path.sep
        except:
            pass

        file_ext_ind = os.path.basename(self.filename_path)[::-1].find(".")
        self.prefix = os.path.basename(self.filename_path)[:-(file_ext_ind+1)]
        self.suffix = "crossCorr"+self.kernel_type

        if self.kernel_type is not None:
            self.ny_PSF = 20 # should be even
            self.nx_PSF = 20 # should be even
            # Define the PSF as a gaussian
            if self.kernel_type == "gaussian":
                if self.kernel_para == None:
                    self.kernel_para = 1.25
                    if not self.mute:
                        print("Default width sigma = {0} used for the gaussian".format(self.kernel_para))

                if not self.mute:
                    print("Generate gaussian PSF")
                # Build the grid for PSF stamp.
                x_PSF_grid, y_PSF_grid = np.meshgrid(np.arange(0,self.ny_PSF,1)-self.ny_PSF/2,
                                                     np.arange(0,self.nx_PSF,1)-self.nx_PSF/2)

                self.PSF = kppmath.gauss2d(x_PSF_grid, y_PSF_grid,1.0,0.0,0.0,self.kernel_para,self.kernel_para)

            # Define the PSF as an aperture or "hat" function
            if self.kernel_type == "hat":
                if self.kernel_para == None:
                    self.kernel_para = 1.5
                    if not self.mute:
                        print("Default radius = {0} used for the hat function".format(self.kernel_para))

                # Build the grid for PSF stamp.
                x_PSF_grid, y_PSF_grid = np.meshgrid(np.arange(0,self.ny_PSF,1)-self.ny_PSF/2,
                                                     np.arange(0,self.nx_PSF,1)-self.nx_PSF/2)
                # Use aperture for the cross correlation.
                # Calculate the corresponding hat function
                self.PSF = kppmath.hat(x_PSF_grid, y_PSF_grid, self.kernel_para)

            if isinstance(self.kernel_type, np.ndarray):
                self.PSF = self.kernel_type

            self.PSF = self.PSF / np.sqrt(np.nansum(self.PSF**2))

        return init_out

    def check_existence(self):
        """
        Return whether or not a filename of the processed data can be found.

        If overwrite is True, the output is always false.

        Return: boolean
        """

        file_exist = (len(glob(self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits')) >= 1)

        if file_exist and not self.mute:
            print("Output already exist: "+self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits')

        if self.overwrite and not self.mute:
            print("Overwriting is turned ON!")

        return file_exist and not self.overwrite


    def calculate(self):
        """
        Perform a cross correlation on the current loaded file.

        :return: Processed image.
        """
        if not self.mute:
            print("~~ Calculating "+self.__class__.__name__+" with parameters " + self.suffix+" ~~")

        if self.collapse:
            if self.weights is not None:
                image_collapsed = np.zeros((self.ny,self.nx))
                for k in range(self.nl):
                    image_collapsed = image_collapsed + self.weights[k]*self.image[k,:,:]
                self.image = image_collapsed/np.sum(self.weights)
            else:
                self.image = np.nanmean(self.image,axis=0)

        if self.nans2zero:
            where_nans = np.where(np.isnan(self.image))
            self.image = np.nan_to_num(self.image)

        # We have to make sure the PSF dimensions are odd because correlate2d shifts the image otherwise...
        if (self.nx_PSF % 2 ==0):
            PSF_tmp = np.zeros((self.ny_PSF,self.nx_PSF+1))
            PSF_tmp[0:self.ny_PSF,0:self.nx_PSF] = self.PSF
            self.PSF = PSF_tmp
            self.nx_PSF = self.nx_PSF +1
        if (self.ny_PSF % 2 ==0):
            PSF_tmp = np.zeros((self.ny_PSF+1,self.nx_PSF))
            PSF_tmp[0:self.ny_PSF,0:self.nx_PSF] = self.PSF
            self.PSF = PSF_tmp
            self.ny_PSF = self.ny_PSF +1


        if self.kernel_type is not None:
            # Check if the input file is 2D or 3D
            if np.size(self.image.shape) == 3: # If the file is a 3D cube
                self.image_convo = np.zeros(self.image.shape)
                for l_id in np.arange(self.nl):
                    self.image_convo[l_id,:,:] = correlate2d(self.image[l_id,:,:],self.PSF,mode="same")
            else: # image is 2D
                self.image_convo = correlate2d(self.image,self.PSF,mode="same")

        if self.nans2zero:
            self.image_convo[where_nans] = np.nan

        return self.image_convo


    def save(self):
        """
        Save the processed files as:
        #user_outputDir#+os.path.sep+"kpop_"+self.label+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits'

        :return: None
        """

        if not os.path.exists(self.outputDir+os.path.sep+self.folderName):
            os.makedirs(self.outputDir+os.path.sep+self.folderName)

        if not self.mute:
            print("Saving: "+self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits')
        hdulist = pyfits.HDUList()

        if hasattr(self,"prihdr"):
            hdulist.append(pyfits.PrimaryHDU(header=self.prihdr))
        else:
            hdulist.append(pyfits.ImageHDU(data=self.image_convo, name=self.suffix))

        if hasattr(self,"exthdr"):
            # Save the parameters as fits keywords
            self.exthdr["KPPFILEN"] = os.path.basename(self.filename_path)
            self.exthdr["KPPFOLDN"] = self.folderName
            self.exthdr["KPPLABEL"] = self.label
            
            self.exthdr["KPPKERTY"] = str(self.kernel_type)
            self.exthdr["KPPKERWI"] = str(self.kernel_para)
            self.exthdr["KPPCOLLA"] = str(self.collapse)
            # Problem with non ASCII characters in np.array2string(self.weights). I don't really understand.
            # if self.weights is not None:
            #     self.exthdr["KPPWEIGH"] = np.array2string(self.weights)
            self.exthdr["KPPNAN2Z"] = str(self.nans2zero)

            hdulist.append(pyfits.ImageHDU(header=self.exthdr, data=self.image_convo, name=self.suffix))
        else:
            hdulist.append(pyfits.ImageHDU(name=self.suffix))

            hdulist[1].header["KPPFILEN"] = os.path.basename(self.filename_path)
            hdulist[1].header["KPPFOLDN"] = self.folderName
            hdulist[1].header["KPPLABEL"] = self.label

            hdulist[1].header["KPPKERTY"] = str(self.kernel_type)
            hdulist[1].header["KPPKERWI"] = str(self.kernel_para)
            hdulist[1].header["KPPCOLLA"] = str(self.collapse)
            # Problem with non ASCII characters in np.array2string(self.weights). I don't really understand.
            # if self.weights is not None:
            #     hdulist[1].header["KPPWEIGH"] = np.array2string(self.weights)
            hdulist[1].header["KPPNAN2Z"] = str(self.nans2zero)

        hdulist.writeto(self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits', clobber=True)

        return None

    def load(self):
        """

        :return: None
        """

        return None