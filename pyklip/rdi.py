import numpy as np
from astropy.io import fits
import os.path
from sys import stdout

class PSFLibrary(object):
    """
    This is an PSF Library to use for reference differential imaging

    Attributes:
        master_library (np.ndarray): aligned library of PSFs. 3-D cube of dim = [N, y, x]. Where N is ALL files
        aligned_center (array-like): a (x,y) coordinate specifying common center the library is aligned to
        master_filenames (np.ndarray): array of N filenames for each frame in the library. Should match with
                                pyklip.instruments.Data.filenames for cross-matching
        master_correlation (np.ndarray): N x N array of correlations between each 2 frames
        master_wvs (np.ndarray): N wavelengths for each frame
        nfiles (int): the number of files in the PSF library
        dataset (pyklip.instruments.Instrument.Data)
        correlation (np.ndarray): N_data x M array of correlations between each 2 frames where M are the selected frames
                            and N_data is the number of files in the dataset. Along the N_data dimension, files are
                            ordered in the same way as the dataset object
        isgoodpsf (np.ndarray): array of N indicating which M PSFs are good for this dataset

    """

    def __init__(self, data, aligned_center, filenames, correlation_matrix=None, wvs=None, compute_correlation=False):
        """

        Args:
            data (np.ndarray): a 3-D cube of PSF library files (dim = [N, y, x]) where N is number of files
                   These files should have already been registered to a common center
            aligned_center (array-like): an (x,y) coordinate specifying the common center all files are registered to
            filenames (np.ndarray): a array of N filenames for each file. These should be in the same format as a
                        pyklip.instruments.Instrument.Data.filenames array so that the two can be cross-matched
            correlation_matrix (np.ndarray): an N x N matrix that expresses the correlation between each two frames in library
            wvs (np.ndarray): array of N wavelengths that correspond to the wavelengths of the library
            compute_correlation (boolean): if True, compute the correlation matrix. Note that this can potentially take a
                                    long time, so you really should be doing it once and saving it
        """
        # call init() of super class
        super(PSFLibrary, self).__init__()

        # Do some checking to make sure the data, filenames list and correlation_matrix (if it exists)
        # all have the same number of files. 
        nfiles_data = np.shape(data)[0]
        nfiles_list = np.shape(filenames)[0]

        if nfiles_data != nfiles_list:
            raise AttributeError("The number of files in the data array and filenames list aren't the same. Something is wrong")

        if correlation_matrix is not None:
            nfiles_correlation = np.shape(correlation_matrix)[0]
            if nfiles_correlation != nfiles_data: 
                raise AttributeError("The number of files in the correlation matrix and in the data array aren't the same. Something is wrong")

        # generate master list of files and meta data from inputs
        self.master_library = data
        self.aligned_center = aligned_center
        self.master_filenames = np.asarray(filenames)

        self.master_correlation = correlation_matrix
        self.master_wvs = wvs
        self.nfiles = nfiles_data
        # fields in the context of a specific dataset
        self.dataset = None
        self.correlation = None
        self.isgoodpsf = None

        # check if correlation matrix was passed in
        if correlation_matrix is None and not compute_correlation:
            raise AttributeError("You didn't pass in a correlation matrix, which means it needs to be computed. Are you "
                                 "sure you want to do this? (This may take a while if you have 10,000+ files)")
        elif compute_correlation:
            self._compute_correlation()

    def _compute_correlation(self, verbose=False, force=False):
        """
        Computes the correlation matrix and saves it in self.master_correlation

        This computes the correlation between two psfs for every pair of psfs in the library. 
        This correlation matrix can be used for the selection of PSFs ahead of time, but as of right now
        it isn't super useful for saving time (e.g. when there are subsections the covariance still needs
        to be recomputed with all the PSFs currently being used).

        """

        #Get the number of files

        if np.size(self.master_correlation) > 1: 
            print "WARNING: your mater_correlation matrix already has data in it"

            if not force:
                print "WARNING: If you want to overwrite the correlation matrix set the 'force' flag to True"
                return
            else: 
                print "WARNING: overwriting master_correlation"


        self.master_correlation=np.zeros([self.nfiles,self.nfiles])

        if verbose:
            print "Making correlation matrix"


        #Loop the correlation matrix calculation
        for i in np.arange(0,nfiles-1):
            self.master_correlation[i,i]=1.

            #TODO: PARALLELIZE THIS STEP. 

            #Cycle through every file that comes AFTER the current file 
            for j in np.arange(i+1,nfiles-1):

                if super_verbose:
                    # print "Correlating file "+ str(i) + " with file "+str(j) + "  \r"
                    stdout.write("\r Correlating file {i}% with file {i}%".format(i,j))
                    stdout.flush()
                
                #Ditch where either of the two arrays have NANs
                where_not_nans = (data_array[:,:,i] == data_array[:,:,i]) & (data_array[:,:,j] == data_array[:,:,j])

                data1= data_array[:,:,i]
                data2= data_array[:,:,j]

                #I believe this bit was copied and pasted from pyklip at some point. 
                covar_psfs=np.cov([data2[where_not_nans], data1[where_not_nans]])
                covar_diag = np.diagflat(1./np.sqrt(np.diag(covar_psfs)))
                corr_psfs = np.dot( np.dot(covar_diag, covar_psfs ), covar_diag)

                self.master_correlation[i,j]=corr_psfs[0,1]
                self.master_correlation[j,i]=corr_psfs[0,1]

        if verbose:
            print "Done making correlation matrix"


    def save_correlation(self, filename, clobber=False, format="fits"):
        """
        Saves self.correlation to a file specified by filename
        Args:
            filename (str): filepath to store the correlation matrix
            format (str): type of file to store the correlation matrix as. Supports numpy?/fits?/pickle? (TBD)

        """

        #TODO: We should probably save more information into the header here, but what exactly it'll be is TBD
        if format == "fits":
            if os.path.isfile(filename):
            #If the file already exists give user warning.     
                if clobber:
                    hdu = fits.PrimaryHDU(self.master_correlation)
                    hdu.writeto(filename, clobber=clobber)
                else: 
                    print "save_correlation: File already exists. Set clobber=True to overwrite"
            
        #But for now only fits
        else:
            print "Sorry, fits is the only filetype type currently supported for saving correlation matrices"
            
    
    def prepare_library(self, dataset, badfiles=None):
        """
        Prepare the PSF Library for an RDI reduction of a specific dataset by only taking the part of the
        library we need.

        Args:
            dataset (pyklip.instruments.Instrument.Data):
            badfiles (np.ndarray): a list of filenames corresponding to bad files we want to also exclude

        Returns:

        """

        # we need to exclude bad files and files already in the dataset itself (since that'd be ADI/SDI/etc)
        # strip away the directories in the master_filenames
        master_just_filenames = np.asarray([filename.split('/')[-1] for filename in self.master_filenames])
        dataset_just_filenames = np.asarray([filename.split('/')[-1] for filename in dataset.filenames])
        # compare with the dataset filnames (also d)
        in_dataset = np.in1d(master_just_filenames, dataset_just_filenames)
        
        # don't compare directly with None
        if badfiles is None:
            badfiles = np.full(np.shape(self.master_filenames), False, dtype=bool)
        are_bad = np.in1d(self.master_filenames, badfiles)
        
        # good ones are the ones that don't fall in either category
        isgood = ~in_dataset & ~badfiles
        good = np.where(isgood)[0]

        # create a view on the good files

        # figure out how the ordering of dataset files are in the PSF library compared to the dataset
        # we want to match the dataset
        # filenames_of_dataset_in_lib = self.master_filenames[np.where(in_dataset)]
        filenames_of_dataset_in_lib = self.master_filenames[in_dataset]
        dataset_file_indices_in_lib = []
        for filename in filenames_of_dataset_in_lib:
            index = np.where(filename == self.master_filenames)[0][0]
            dataset_file_indices_in_lib.append(index)

        if np.size(dataset_file_indices_in_lib) < 1:
            print "Dataset not found in PSF Library, library not prepared."
        else:
            dataset_file_indices_in_lib = np.array(dataset_file_indices_in_lib)
            # generate a correlation matrix that's N_dataset x N_goodpsfs
            # the ordering of the correlation matrix also ensures that N_dataset is ordered the same as datasets
            self.correlation = self.master_correlation[np.ix_(dataset_file_indices_in_lib, good)]

            # generate a list indicating which files are good
            self.isgoodpsf = good