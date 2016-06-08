__author__ = 'jruffio'
import os
import astropy.io.fits as pyfits
from glob import glob
import multiprocessing as mp
import numpy as np
from scipy.signal import convolve2d

import matplotlib.pyplot as plt

from pyklip.kpp.utils.kppSuperClass import KPPSuperClass
from pyklip.kpp.stat.statPerPix_utils import *
from pyklip.kpp.utils.GOI import *
from pyklip.kpp.utils.GPIimage import *

class ContrastFMMF(KPPSuperClass):
    """
    Class for SNR calculation.
    """
    def __init__(self,filename,
                 inputDir = None,
                 outputDir = None,
                 mute=None,
                 N_threads=None,
                 label = None,
                 mask_radius = None,
                 IOWA = None,
                 GOI_list_folder = None,
                 overwrite = False,
                 contrast_filename = None):
        """


        :param filename: Filename of the file on which to calculate the metric. It should be the complete path unless
                        inputDir is defined.
                        It can include wild characters. The file will be selected using the first output of glob.glob().
        :param mute: If True prevent printed log outputs.
        :param N_threads: Number of threads to be used for the metrics and the probability calculations.
                        If None use mp.cpu_count().
                        If -1 do it sequentially.
                        Note that it is not used for this super class.
        :param label: Define the suffix to the output folder when it is not defined. cf outputDir. Default is "default".
        """
        # allocate super class
        super(ContrastFMMF, self).__init__(filename,
                                     inputDir = inputDir,
                                     outputDir = outputDir,
                                     folderName = None,
                                     mute=mute,
                                     N_threads=N_threads,
                                     label=label,
                                     overwrite = overwrite)

        if mask_radius is None:
            self.mask_radius = 3
        else:
            self.mask_radius = mask_radius

        self.IOWA = IOWA
        self.N = 400
        self.Dr = 4
        self.type = "stddev"
        self.suffix = "2Dcontrast"
        self.GOI_list_folder = GOI_list_folder
        self.contrast_filename = contrast_filename


    def initialize(self,inputDir = None,
                         outputDir = None,
                         folderName = None,
                         compact_date = None,
                         label = None):
        """
        Initialize the non general inputs that are needed for the metric calculation and load required files.

        For this super class it simply reads the input file including fits headers and store it in self.image.
        One can also overwrite inputDir, outputDir which is basically the point of this function.
        The file is assumed here to be a fits containing a 2D image or a GPI 3D cube (assumes 37 spectral slice).

        Example for inherited classes:
        It can read the PSF cube or define the hat function.
        It can also read the template spectrum in a 3D scenario.
        It could also overwrite this function in case it needs to read multiple files or non fits file.

        :param inputDir: If defined it allows filename to not include the whole path and just the filename.
                        Files will be read from inputDir.
                        Note tat inputDir might be redefined using initialize at any point.
                        If inputDir is None then filename is assumed to have the absolute path.
        :param outputDir: Directory where to create the folder containing the outputs.
                        Note tat inputDir might be redefined using initialize at any point.
                        If outputDir is None:
                            If inputDir is defined: outputDir = inputDir+os.path.sep+"planet_detec_"
        :param folderName: Name of the folder containing the outputs. It will be located in outputDir.
                        Default folder name is "default_out".
                        The convention is to have one folder per spectral template.
                        If the keyword METFOLDN is available in the fits file header then the keyword value is used no
                        matter the input.
        :param label: Define the suffix to the output folder when it is not defined. cf outputDir. Default is "default".

        :return: None
        """
        if not self.mute:
            print("~~ INITializing "+self.__class__.__name__+" ~~")
        # The super class already read the fits file
        init_out = super(ContrastFMMF, self).initialize(inputDir = inputDir,
                                         outputDir = outputDir,
                                         folderName = folderName,
                                         label=label)

        if self.contrast_filename is not None:
            # Check file existence and define filename_path
            if self.inputDir is None:
                try:
                    if len(glob(self.contrast_filename)) == self.N_matching_files:
                        self.contrast_filename_path = os.path.abspath(glob(self.contrast_filename)[self.id_matching_file-1])
                    else:
                        self.contrast_filename_path = os.path.abspath(glob(self.contrast_filename)[0])
                except:
                    raise Exception("File "+self.contrast_filename+"doesn't exist.")
            else:
                try:
                    if len(glob(self.inputDir+os.path.sep+self.contrast_filename)) == self.N_matching_files:
                        self.contrast_filename_path = os.path.abspath(glob(self.inputDir+os.path.sep+self.contrast_filename)[self.id_matching_file-1])
                    else:
                        self.contrast_filename_path = os.path.abspath(glob(self.inputDir+os.path.sep+self.contrast_filename)[0])
                except:
                    raise Exception("File "+self.inputDir+os.path.sep+self.contrast_filename+" doesn't exist.")


        # Get center of the image (star position)
        try:
            # Retrieve the center of the image from the fits headers.
            self.center = [self.exthdr['PSFCENTX'], self.exthdr['PSFCENTY']]
        except:
            # If the keywords could not be found the center is defined as the middle of the image
            if not self.mute:
                print("Couldn't find PSFCENTX and PSFCENTY keywords.")
            self.center = [(self.nx-1)/2,(self.ny-1)/2]


        try:
            self.folderName = self.exthdr["METFOLDN"]+os.path.sep
        except:
            pass

        file_ext_ind = os.path.basename(self.filename_path)[::-1].find(".")
        self.prefix = os.path.basename(self.filename_path)[:-(file_ext_ind+1)]

        return init_out

    def check_existence(self):
        """

        :return: False
        """

        file_exist = (len(glob(self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits')) >= 1)

        if file_exist and not self.mute:
            print("Output already exist: "+self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits')

        if self.overwrite and not self.mute:
            print("Overwriting is turned ON!")

        return file_exist and not self.overwrite


    def calculate(self):
        """

        :param N: Defines the width of the ring by the number of pixels it has to contain
        :return: self.image the imput fits file.
        """
        if not self.mute:
            print("~~ Calculating "+self.__class__.__name__+" with parameters " + self.suffix+" ~~")

        # If GOI_list_folder is not None. Mask the known objects from the image that will be used for calculating the
        # PDF. This masked image is given separately to the probability calculation function.
        if self.GOI_list_folder is not None:
            self.image_without_planet = mask_known_objects(self.image,self.prihdr,self.exthdr,self.GOI_list_folder, mask_radius = self.mask_radius)
        else:
            self.image_without_planet = self.image

        self.flux_1Dstddev,self.flux_stddev_rSamp = get_image_stddev(self.image_without_planet,
                                                                     self.IOWA,
                                                                     N = None,
                                                                     centroid = self.center,
                                                                     r_step = self.Dr/2,
                                                                     Dr=self.Dr)
        self.flux_stddev_rSamp = np.array([r_tuple[0] for r_tuple in self.flux_stddev_rSamp])
        self.flux_1Dstddev = np.array(self.flux_1Dstddev)
        self.flux_1Dstddev_map = get_image_stat_map(self.image,
                                                    self.image_without_planet,
                                                    IOWA = self.IOWA,
                                                    N = None,
                                                    centroid = self.center,
                                                    r_step = self.Dr/2,
                                                    Dr = self.Dr,
                                                    type = "stddev",
                                                    image_wide = None)


        self.fluxMap_stddev = get_image_stat_map_perPixMasking(self.image,
                                                         self.image_without_planet,
                                                         mask_radius = self.mask_radius,
                                                         IOWA = self.IOWA,
                                                         N = self.N,
                                                         centroid = self.center,
                                                         mute = self.mute,
                                                         N_threads = self.N_threads,
                                                         Dr= self.Dr,
                                                         Dth = None,
                                                         type = self.type)


        legend_str_list = []
        plt.figure(1,figsize=(12,6))
        plt.subplot(1,2,1)
        if self.contrast_filename is not None:
            with open(self.contrast_filename_path, 'rt') as cvs_contrast:
                cvs_contrast_reader = csv.reader(filter(lambda row: row[0]!="#",cvs_contrast),delimiter=' ')
                list_contrast = list(cvs_contrast_reader)
                contrast_str_arr = np.array(list_contrast, dtype='string')
                col_names = contrast_str_arr[0]
                contrast_arr = contrast_str_arr[1::].astype(np.float)
                self.sep_samples = contrast_arr[:,0]
                self.Ttype_contrast = np.squeeze(contrast_arr[:,np.where("T-Type"==col_names)])
                self.Ltype_contrast = np.squeeze(contrast_arr[:,np.where("L-Type"==col_names)])


                plt.plot(self.sep_samples,self.Ttype_contrast,"--", color='b', linewidth=3.0)
                legend_str_list.append("T-type pyklip")
                plt.plot(self.sep_samples,self.Ltype_contrast,"--", color='r', linewidth=3.0)
                legend_str_list.append("L-type pyklip")

        plt.plot(self.flux_stddev_rSamp*0.01413,5*self.flux_1Dstddev, color='r', linewidth=3.0)
        legend_str_list.append("{0} FMpF".format(self.folderName))
        plt.xlabel("Separation (arcsec)", fontsize=20)
        plt.ylabel("Contrast (log10)", fontsize=20)
        plt.legend(legend_str_list)
        ax= plt.gca()
        ax.set_yscale('log')
        ax.tick_params(axis='x', labelsize=20)
        ax.tick_params(axis='y', labelsize=20)
        # ax.spines['right'].set_visible(False)
        # ax.spines['top'].set_visible(False)
        # ax.xaxis.set_ticks_position('bottom')
        # ax.yaxis.set_ticks_position('left')

        plt.subplot(1,2,2)
        plt.imshow(5*(self.fluxMap_stddev-self.flux_1Dstddev_map))
        plt.colorbar()
        ax = plt.gca()
        # Remove box and axes ticks
        ax.set_axis_off()
        # rect = fig.patch
        # rect.set_facecolor('white')

        return self.fluxMap_stddev


    def save(self):
        """

        :return: None
        """

        if not os.path.exists(self.outputDir+os.path.sep+self.folderName):
            os.makedirs(self.outputDir+os.path.sep+self.folderName)


        self.suffix = "1Dcontrast"
        if not self.mute:
            print("Saving: "+self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.png')
        plt.savefig(self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+".png", bbox_inches='tight')

        if hasattr(self,"prihdr") and hasattr(self,"exthdr"):
            # Save the parameters as fits keywords
            # STA##### stands for STAtistic
            self.exthdr["STA_TYPE"] = self.type

            self.exthdr["STAFILEN"] = self.filename_path
            self.exthdr["STAINDIR"] = self.inputDir
            self.exthdr["STAOUTDI"] = self.outputDir
            self.exthdr["STAFOLDN"] = self.folderName

            self.exthdr["STAMASKR"] = self.mask_radius
            self.exthdr["STA_IOWA"] = str(self.IOWA)
            self.exthdr["STA_N"] = self.N
            self.exthdr["STA_DR"] = self.Dr
            self.exthdr["STA_TYPE"] = self.type
            self.exthdr["STAGOILF"] = self.GOI_list_folder

            # # This parameters are not always defined
            # if hasattr(self,"spectrum_name"):
            #     self.exthdr["STASPECN"] = self.spectrum_name

            self.suffix = "2Dcontrast"
            if not self.mute:
                print("Saving: "+self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits')
            hdulist = pyfits.HDUList()
            hdulist.append(pyfits.PrimaryHDU(header=self.prihdr))
            hdulist.append(pyfits.ImageHDU(header=self.exthdr, data=self.fluxMap_stddev, name=self.suffix))
            hdulist.writeto(self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits', clobber=True)
        else:
            hdulist = pyfits.HDUList()
            hdulist.append(pyfits.ImageHDU(data=self.fluxMap_stddev, name=self.suffix))
            hdulist.append(pyfits.ImageHDU(name=self.suffix))

            hdulist[1].header["STA_TYPE"] = self.type

            hdulist[1].header["STAFILEN"] = self.filename_path
            hdulist[1].header["STAINDIR"] = self.inputDir
            hdulist[1].header["STAOUTDI"] = self.outputDir
            hdulist[1].header["STAFOLDN"] = self.folderName

            hdulist[1].header["STAMASKR"] = self.mask_radius
            hdulist[1].header["STA_IOWA"] = self.IOWA
            hdulist[1].header["STA_N"] = self.N
            hdulist[1].header["STA_DR"] = self.Dr
            hdulist[1].header["STA_TYPE"] = self.type
            hdulist[1].header["STAGOILF"] = self.GOI_list_folder

            self.suffix = "2Dcontrast"
            if not self.mute:
                print("Saving: "+self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits')
            hdulist.writeto(self.outputDir+os.path.sep+self.folderName+os.path.sep+self.prefix+'-'+self.suffix+'.fits', clobber=True)

        plt.close(1)

        return None

    def load(self):
        """

        :return: None
        """

        return None