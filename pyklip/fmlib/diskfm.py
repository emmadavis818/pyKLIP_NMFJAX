import sys
import multiprocessing as mp
import numpy as np
import os
import copy
import pickle
import h5py
import deepdish as dd

import glob
import scipy.ndimage as ndimage
import ctypes

from pyklip.fmlib.nofm import NoFM
import pyklip.fm as fm
from pyklip.klip import rotate
import itertools

parallel = True 

class DiskFM(NoFM):
    def __init__(self, inputs_shape, numbasis, dataset, model_disk, basis_filename = 'klip-basis.h5', 
                        load_from_basis = False, save_basis = False, annuli = None, subsections = None, 
                        numthreads = None, mode = 'ADI'):
        '''
        Takes an input model and runs KLIP-FM. Can be used in MCMCs by saving the basis 
        vectors. When disk is updated, FM can be run on the new disk without computing new basis
        vectors. 

        For first time, instantiate DiskFM with no save_basis and nominal model disk.
        Specify number of annuli and subsections used to save basis vectors

        Currently only supports mode = ADI
        '''
        
        if hasattr(numbasis, "__len__"):
            numbasis = np.array(numbasis)
        else:
            numbasis = np.array([numbasis])


        if hasattr(inputs_shape, "__len__"):
            inputs_shape = np.array(inputs_shape)
        else:
            inputs_shape = np.array([inputs_shape])

        super(DiskFM, self).__init__(inputs_shape, numbasis)

        # Attributes of input/output
        self.inputs_shape = dataset.input.shape
        # self.inputs_shape = inputs_shape
        
        # print(dataset.klipparams["numbasis"])
        # print(numbasis)
        self.numbasis = numbasis

        self.numims = dataset.input.shape[0]
        self.mode = mode

        # Input dataset attributes
        self.dataset = dataset
        self.IWA = dataset.IWA
        self.images = dataset.input
        self.pas = dataset.PAs
        self.centers = dataset.centers
        self.wvs = dataset.wvs

        # Outputs attributes
        output_imgs_shape = self.images.shape + self.numbasis.shape
        self.output_imgs_shape = output_imgs_shape
        self.outputs_shape = output_imgs_shape
        self.np_data_type = ctypes.c_float

        # Coords where align_and_scale places model center (default is inputs center).
        # if aligned_center is None:
        #     aligned_center = [int(dataset.input.shape[2]//2), int(dataset.input.shape[1]//2)]
        self.aligned_center = dataset.output_centers[0]
        if self.aligned_center is None:
            self.aligned_center = [int(self.inputs_shape[2]//2), int(self.inputs_shape[1]//2)]

        # Make disk reference PSFS
        self.update_disk(model_disk)

        self.save_basis = save_basis
        self.annuli = annuli
        self.subsections = subsections

        self.basis_filename = basis_filename
        self.load_from_basis = load_from_basis

        x,y = np.meshgrid(np.arange(self.inputs_shape[2] * 1.0),np.arange(self.inputs_shape[1]*1.0))
        nanpix = np.where(np.isnan(dataset.input[0]))
        
        self.OWA = dataset.OWA
        
        if self.OWA is None:
            if np.size(nanpix) == 0:
                self.OWA = np.sqrt(np.max((x - self.centers[0][0]) ** 2 + (y - self.centers[0][1]) ** 2))
            else:
                # grab the NaN from the 1st percentile (this way we drop outliers)
                self.OWA = np.sqrt(np.percentile((x[nanpix] - self.centers[0][0]) ** 2 + (y[nanpix] - self.centers[0][1]) ** 2, 1))


        if numthreads == None:
            self.numthreads = mp.cpu_count()
        else:
            self.numthreads = numthreads

        if self.save_basis == True:
            # Need to know r and phi indicies in fm from eigen
            assert annuli is not None, "need annuli keyword to save basis"
            assert subsections is not None, "need subsections keyword to save basis"
            self.dr = (self.OWA - self.IWA) / annuli
            self.dphi = 2 * np.pi / subsections
            
            # Set up dictionaries for saving basis
            manager = mp.Manager()
            global klmodes_dict, evecs_dict, evals_dict, ref_psfs_indicies_dict, section_ind_dict
            global radstart_dict, radend_dict, phistart_dict, phiend_dict, input_img_num_dict

            klmodes_dict = manager.dict()
            evecs_dict = manager.dict()
            evals_dict = manager.dict()
            ref_psfs_indicies_dict = manager.dict()
            section_ind_dict = manager.dict()
            
            radstart_dict = manager.dict()
            radend_dict = manager.dict()
            phistart_dict = manager.dict()
            phiend_dict = manager.dict()
            input_img_num_dict = manager.dict()

        if load_from_basis is True:
            self.load_basis_files(basis_filename)


    def alloc_fmout(self, output_img_shape):
        ''' 
       Allocates shared memory for output image 
        '''
        fmout_size = int(np.prod(output_img_shape))
        fmout_shape = output_img_shape
        fmout = mp.Array(self.data_type, fmout_size)
        return fmout, fmout_shape

    
    def alloc_perturbmag(self, output_img_shape, numbasis):
        """
        Allocates shared memory to store the fractional magnitude of the linear KLIP perturbation
        Stores a number for each frame = max(oversub + selfsub)/std(PCA(image))

        Args:
            output_img_shape: shape of output image (usually N,y,x,b)
            numbasis: array/list of number of KL basis cutoffs requested

        Returns:
            perturbmag: mp.array to store linaer perturbation magnitude
            perturbmag_shape: shape of linear perturbation magnitude

        """
        perturbmag_shape = (output_img_shape[0], np.size(numbasis))
        perturbmag = mp.Array(self.data_type, int(np.prod(perturbmag_shape)))

        return perturbmag, perturbmag_shape

    def fm_from_eigen(self, klmodes=None, evals=None, evecs=None, input_img_shape=None, input_img_num=None, 
                            ref_psfs_indicies=None, section_ind=None,section_ind_nopadding=None, aligned_imgs=None, 
                            pas=None, wvs=None, radstart=None, radend=None, phistart=None, phiend=None, 
                            padding=None,IOWA = None, ref_center=None, parang=None, ref_wv=None, numbasis=None, 
                            fmout=None, perturbmag=None, klipped=None, covar_files=None,flipx=True, **kwargs):
        """
        Generate forward models using the KL modes, eigenvectors, and eigenvectors from KLIP. Calls fm.py functions to
        perform the forward modelling

        Args:
            klmodes: unpertrubed KL modes
            evals: eigenvalues of the covariance matrix that generated the KL modes in ascending order
                    (lambda_0 is the 0 index) (shape of [nummaxKL])
            evecs: corresponding eigenvectors (shape of [p, nummaxKL])
            input_image_shape: 2-D shape of inpt images ([ysize, xsize])
            input_img_num: index of sciece frame
            ref_psfs_indicies: array of indicies for each reference PSF
            section_ind: array indicies into the 2-D x-y image that correspond to this section.
                            Note needs be called as section_ind[0]
            pas: array of N parallactic angles corresponding to N reference images [degrees]
            wvs: array of N wavelengths of those referebce images
            radstart: radius of start of segment
            radend: radius of end of segment
            phistart: azimuthal start of segment [radians]
            phiend: azimuthal end of segment [radians]
            padding: amount of padding on each side of sector
            IOWA: tuple (IWA,OWA) where IWA = Inner working angle and OWA = Outer working angle both in pixels.
                It defines the separation interva in which klip will be run.
            ref_center: center of image
            numbasis: array of KL basis cutoffs
            parang: parallactic angle of input image [DEGREES]
            ref_wv: wavelength of science image
            fmout: numpy output array for FM output. Shape is (N, y, x, b)
            perturbmag: numpy output for size of linear perturbation. Shape is (N, b)
            klipped: PSF subtracted image. Shape of ( size(section), b)
            kwargs: any other variables that we don't use but are part of the input
        """
        sci = aligned_imgs[input_img_num, section_ind[0]]

        refs = aligned_imgs[ref_psfs_indicies, :]
        refs = refs[:, section_ind[0]]
        refs[np.where(np.isnan(refs))] = 0

        model_sci = self.model_disks[input_img_num, section_ind[0]]

        model_ref = self.model_disks[ref_psfs_indicies, :]
        model_ref = model_ref[:, section_ind[0]]
        model_ref[np.where(np.isnan(model_ref))] = 0

        delta_KL= fm.perturb_specIncluded(evals, evecs, klmodes, refs, model_ref, return_perturb_covar = False)
        postklip_psf, oversubtraction, selfsubtraction = fm.calculate_fm(delta_KL, klmodes, 
                                                                    numbasis, sci, model_sci, inputflux = None)

        for thisnumbasisindex in range(np.size(numbasis)):
            self._save_rotated_section(input_img_shape, postklip_psf[thisnumbasisindex], section_ind,
                             fmout[input_img_num, :, :,thisnumbasisindex], None, parang,
                             radstart, radend, phistart, phiend, padding,IOWA, ref_center, flipx=flipx) # FIXME

        if self.save_basis is True:

            curr_im = str(input_img_num)
            if len(curr_im) < 4:
                curr_im = '000' + curr_im

            #To have a single identifier for each section, we take the first pixel and the image #
            namkey = 'idsec' + str(section_ind[0][0]) + 'i' + curr_im

            klmodes_dict[namkey] = klmodes
            evals_dict[namkey] = evals
            evecs_dict[namkey] = evecs
            ref_psfs_indicies_dict[namkey] = ref_psfs_indicies
            section_ind_dict[namkey] = section_ind

            radstart_dict[namkey] = radstart
            radend_dict[namkey] = radend
            phistart_dict[namkey] = phistart
            phiend_dict[namkey] = phiend
            input_img_num_dict[namkey] = input_img_num
       
            
    def fm_parallelized(self):
        '''
        Functions like klip_parallelized, but doesn't find new 
        evals and evecs. 
        '''


        fmout_data, fmout_shape = self.alloc_fmout(self.output_imgs_shape)
        fmout_np = fm._arraytonumpy(fmout_data, fmout_shape, dtype = self.np_data_type)
        
        for key in self.dict_keys:
            
            radstart = self.radstart_dict[key]
            radend = self.radend_dict[key]
            phistart = self.phistart_dict[key]
            phiend = self.phiend_dict[key]
            img_num = self.input_img_num_dict[key]
 
            section_ind = self.section_ind_dict[key]
            sector_size = np.size(section_ind)
            original_KL = self.klmodes_dict[key]
            evals = self.evals_dict[key]
            evecs = self.evecs_dict[key]
            ref_psfs_indicies = self.ref_psfs_indicies_dict[key] 
            
            wvs = self.wvs
            unique_wvs = np.unique(wvs)
            wl_here = wvs[img_num]
            wv_index = (np.where(unique_wvs == wl_here))[0][0]
            aligned_imgs_for_this_wl = self.aligned_imgs_np[wv_index]
            original_imgs_shape = self.images.shape
        
            if parallel:
                self.fm_from_eigen(klmodes=original_KL, evals=evals, evecs=evecs,
                                   input_img_shape=[original_imgs_shape[1], original_imgs_shape[2]], 
                                   input_img_num=img_num, ref_psfs_indicies=ref_psfs_indicies, 
                                   section_ind=section_ind, aligned_imgs=aligned_imgs_for_this_wl,
                                   pas=self.pa_imgs_np[ref_psfs_indicies], wvs=self.wvs_imgs_np[ref_psfs_indicies], 
                                   radstart=radstart, radend=radend, phistart=phistart, phiend=phiend, 
                                   padding=0.,IOWA = (self.IWA, self.OWA), ref_center=self.aligned_center,
                                   parang=self.pa_imgs_np[img_num], ref_wv=None, numbasis=self.numbasis,
                                   fmout=fmout_np,perturbmag = None, klipped=None, covar_files=None)

            else:
                pass

        fmout_np = fm._arraytonumpy(fmout_data, fmout_shape, dtype = self.np_data_type)
        fmout_np = self.cleanup_fmout(fmout_np)

        #Check if we have a disk model at multiple wavelengths
        model_disk_shape = np.shape(self.model_disk)        
        #If true then it's a non collapsed spec mode disk and save indivudal specmode cubes for each KL mode
        if np.size(model_disk_shape) > 2: 

            nfiles = int(np.nanmax(self.dataset.filenums))+1 #Get the number of files  
            n_wv_per_file = int(self.inputs_shape[0]/nfiles) #Number of wavelenths per file. 

            ##Collapse across all files, keeping the wavelengths intact. 
            fmout_return = np.zeros([np.size(self.numbasis),n_wv_per_file,self.inputs_shape[1],self.inputs_shape[2]])
            for i in np.arange(n_wv_per_file):
                fmout_return[:,i,:,:] = np.nansum(fmout_np[:,i::n_wv_per_file,:,:], axis =1)/nfiles
            
        else:
            #If false then this is a collapsed spec mode or pol mode: collapsed across all files (and wavelenths)
            fmout_return = np.nanmean(fmout_np, axis = 1) 

        return fmout_return
  
        
    def load_basis_files(self, basis_file_pattern):
        '''
        Loads in previously saved basis files and sets variables for fm_from_eigen
        '''
        _, file_extension = os.path.splitext(basis_file_pattern)
        
        # Load in file
        if file_extension == '.pkl':
            f = open(basis_file_pattern, 'rb')
            if sys.version_info.major == 3:
                self.klmodes_dict = pickle.load(f, encoding='latin1')
                self.evecs_dict = pickle.load(f, encoding='latin1')
                self.evals_dict = pickle.load(f, encoding='latin1')
                self.ref_psfs_indicies_dict = pickle.load(f, encoding='latin1')
                self.section_ind_dict = pickle.load(f, encoding='latin1')

                self.radstart_dict = pickle.load(f, encoding='latin1')
                self.radend_dict = pickle.load(f, encoding='latin1')
                self.phistart_dict = pickle.load(f, encoding='latin1')
                self.phiend_dict = pickle.load(f, encoding='latin1')
                self.input_img_num_dict = pickle.load(f, encoding='latin1')

            else:
                self.klmodes_dict = pickle.load(f)
                self.evecs_dict = pickle.load(f)
                self.evals_dict = pickle.load(f)
                self.ref_psfs_indicies_dict = pickle.load(f)
                self.section_ind_dict = pickle.load(f)

                self.radstart_dict = pickle.load(f)
                self.radend_dict = pickle.load(f)
                self.phistart_dict = pickle.load(f)
                self.phiend_dict = pickle.load(f)
                self.input_img_num_dict = pickle.load(f)
        
        if file_extension == '.h5':
            Dict_for_saving_in_h5 = dd.io.load(self.basis_filename)

            self.klmodes_dict = Dict_for_saving_in_h5['klmodes_dict']
            self.evecs_dict = Dict_for_saving_in_h5['evecs_dict']
            self.evals_dict = Dict_for_saving_in_h5['evals_dict']
            self.ref_psfs_indicies_dict = Dict_for_saving_in_h5['ref_psfs_indicies_dict']
            self.section_ind_dict = Dict_for_saving_in_h5['section_ind_dict']

            self.radstart_dict = Dict_for_saving_in_h5['radstart_dict']
            self.radend_dict = Dict_for_saving_in_h5['radend_dict']
            self.phistart_dict = Dict_for_saving_in_h5['phistart_dict']
            self.phiend_dict = Dict_for_saving_in_h5['phiend_dict']
            self.input_img_num_dict = Dict_for_saving_in_h5['input_img_num_dict']
            del Dict_for_saving_in_h5

        # Set extents for each section
        self.dict_keys = sorted(self.klmodes_dict.keys())
        
        # Make flattened images for running paralellized
        original_imgs = mp.Array(self.data_type, np.size(self.images))
        original_imgs_shape = self.images.shape

        original_imgs_np = fm._arraytonumpy(original_imgs, original_imgs_shape,dtype=self.np_data_type)
        original_imgs_np[:] = self.images
        numthreads = self.numthreads

        # make array for recentered/rescaled image for each wavelength                               
        unique_wvs = np.unique(self.wvs)
        recentered_imgs = mp.Array(self.data_type, np.size(self.images)*np.size(unique_wvs))
        recentered_imgs_shape = (np.size(unique_wvs),) + self.images.shape

        # remake the PA, wv, and center arrays as shared arrays                  
        pa_imgs = mp.Array(self.data_type, np.size(self.pas))
        pa_imgs_np = fm._arraytonumpy(pa_imgs,dtype=self.np_data_type)
        pa_imgs_np[:] = self.pas
        wvs_imgs = mp.Array(self.data_type, np.size(self.wvs))
        wvs_imgs_np = fm._arraytonumpy(wvs_imgs,dtype=self.np_data_type)
        wvs_imgs_np[:] = self.wvs
        centers_imgs = mp.Array(self.data_type, np.size(self.centers))
        centers_imgs_np = fm._arraytonumpy(centers_imgs, self.centers.shape,dtype=self.np_data_type)
        centers_imgs_np[:] = self.centers
        output_imgs = None
        output_imgs_numstacked = None
        output_imgs_shape = self.images.shape + self.numbasis.shape
        self.output_imgs_shape = output_imgs_shape
        self.outputs_shape = output_imgs_shape
        
        # Create Custom Shared Memory array fmout to save output of forward modelling
        fmout_data, fmout_shape = self.alloc_fmout(output_imgs_shape)
        # Create shared memory to keep track of validity of perturbation
        perturbmag, perturbmag_shape = self.alloc_perturbmag(output_imgs_shape,  self.numbasis)


        # align and scale the images for each image. Use map to do this asynchronously]
        tpool = mp.Pool(processes=numthreads, initializer=fm._tpool_init,
                        initargs=(original_imgs, original_imgs_shape, recentered_imgs, recentered_imgs_shape, output_imgs,
                              output_imgs_shape, output_imgs_numstacked, pa_imgs, wvs_imgs, centers_imgs, None, None,
                              fmout_data, fmout_shape,perturbmag,perturbmag_shape), maxtasksperchild=50)

        # # SINGLE THREAD DEBUG PURPOSES ONLY
        if not parallel:
            fm._tpool_init(original_imgs, original_imgs_shape, recentered_imgs, recentered_imgs_shape, output_imgs,
                    output_imgs_shape, output_imgs_numstacked, pa_imgs, wvs_imgs, centers_imgs, None, None,
                    fmout_data, fmout_shape,perturbmag,perturbmag_shape)

    
        print("Begin align and scale images for each wavelength")
        aligned_outputs = []
        for threadnum in range(self.numthreads):
            aligned_outputs += [tpool.apply_async(fm._align_and_scale_subset, 
                                args=(threadnum, self.aligned_center,self.numthreads,self.np_data_type))]         
            #save it to shared memory                                           
        for aligned_output in aligned_outputs:
            aligned_output.wait()

        self.aligned_imgs_np = fm._arraytonumpy(recentered_imgs, 
                shape =  (recentered_imgs_shape[0], 
                            recentered_imgs_shape[1], recentered_imgs_shape[2] * recentered_imgs_shape[3])) 
        self.wvs_imgs_np = wvs_imgs_np
        self.pa_imgs_np = pa_imgs_np

        # After loading it, we stop saving the KL basis to avoid saving it every time we run self.fm_parallelize.
        self.save_basis = False

        # Delete global variables so it can pickle
        del pa_imgs
        del wvs_imgs
        del original_imgs
        del original_imgs_shape
        del original_imgs_np
        del recentered_imgs
        del recentered_imgs_shape
        del centers_imgs_np
        del fmout_data
        del fmout_shape
        del output_imgs
        del output_imgs_shape
        del output_imgs_numstacked
        del centers_imgs
        del wvs_imgs_np
        del pa_imgs_np


    def save_fmout(self, dataset, fmout, outputdir, fileprefix, numbasis, 
                        klipparams=None, calibrate_flux=False, spectrum=None, pixel_weights=1):
        '''
        Uses self.dataset parameters to save fmout, the output of
        fm_paralellized or klip_dataset
        '''

        #Collapsed across all files (and wavelenths) and divide by number of images to keep units as ADU/coadd
        KLmode_cube = np.nanmean(fmout, axis = 1) #/ self.inputs_shape[0] 

        #Check if we have a disk model at multiple wavelengths
        model_disk_shape = np.shape(self.model_disk)        
        #If true then it's a spec mode disk and save indivudal specmode cubes for each KL mode
        if np.size(model_disk_shape) > 2:

            nfiles = int(np.nanmax(self.dataset.filenums))+1 #Get the number of files  
            n_wv_per_file = int(self.inputs_shape[0]/nfiles) #Number of wavelenths per file. 

            ##Collapse across all files, keeping the wavelengths intact. 
            KLmode_spectral_cubes = np.zeros([np.size(numbasis),n_wv_per_file,self.inputs_shape[1],self.inputs_shape[2]])
            for i in np.arange(n_wv_per_file):
                KLmode_spectral_cubes[:,i,:,:] = np.nansum(fmout[:,i::n_wv_per_file,:,:], axis =1)/nfiles
            
            for KLcutoff, spectral_cube in zip(numbasis, KLmode_spectral_cubes):
            #     # calibrate spectral cube if needed
                dataset.savedata(outputdir + '/' + fileprefix + "-fmpsf-KL{0}-speccube.fits".format(KLcutoff),
                                 spectral_cube, klipparams=klipparams.format(numbasis=KLcutoff),
                                 filetype="PSF Subtracted Spectral Cube")


        dataset.savedata(outputdir + '/' + fileprefix + "-fmpsf-KLmodes-all.fits", KLmode_cube,
                         klipparams=klipparams.format(numbasis=str(numbasis)), filetype="KL Mode Cube",
                         zaxis=numbasis)


    def save_kl_basis(self):

        """
        Save the KL basis and other needed parameters

        Args:
            None

        Returns:
            None
        """
        if self.save_basis == True:
            _, file_extension = os.path.splitext(self.basis_filename)
            if file_extension == '.pkl':
                f = open(self.basis_filename, 'wb')
                pickle.dump(dict(klmodes_dict), f, protocol=2)
                pickle.dump(dict(evecs_dict), f, protocol=2)
                pickle.dump(dict(evals_dict), f, protocol=2)
                pickle.dump(dict(ref_psfs_indicies_dict), f, protocol=2)
                pickle.dump(dict(section_ind_dict), f, protocol=2)

                pickle.dump(dict(radstart_dict), f, protocol=2)
                pickle.dump(dict(radend_dict), f, protocol=2)
                pickle.dump(dict(phistart_dict), f, protocol=2)
                pickle.dump(dict(phiend_dict), f, protocol=2)
                pickle.dump(dict(input_img_num_dict), f, protocol=2)
                
            if file_extension == '.h5':
                #make a single dictionnary and save in h5
                Dict_for_saving_in_h5 = {   'klmodes_dict':klmodes_dict, 
                                            'evecs_dict':evecs_dict, 
                                            'evals_dict':evals_dict, 
                                            'ref_psfs_indicies_dict':ref_psfs_indicies_dict, 
                                            'section_ind_dict':section_ind_dict,
                                            'radstart_dict':radstart_dict,
                                            'radend_dict':radend_dict,
                                            'phistart_dict':phistart_dict,
                                            'phiend_dict':phiend_dict,
                                            'input_img_num_dict':input_img_num_dict
                                        }

                dd.io.save(self.basis_filename, Dict_for_saving_in_h5)
                del Dict_for_saving_in_h5
        else:
            pass
 
            
    def cleanup_fmout(self, fmout):

        """
        After running KLIP-FM, we need to reshape fmout so that the numKL dimension is the first one and not the last
        We also use this function to save the KL basis because it is called by fm.py at the end fm.klip_parallelized
        Args:
            fmout: numpy array of ouput of FM

        Returns:
            fmout: same but cleaned up if necessary
        """
        
        self.save_kl_basis()

        dims = fmout.shape
        fmout = np.rollaxis(fmout.reshape((dims[0], dims[1], dims[2], dims[3])), 3)
        return fmout

    def update_disk(self, model_disk):
        '''
        Takes model disk and rotates it to the PAs of the input images for use as reference PSFS
       
        Args: 
             model_disk: Disk to be forward modeled.
             The disk can be either an 3D array of shape (wvs,y,x) for wvs images of shape (y,x)
             or just a 2D Array of shape (y,x), in which case, if the dataset is multiwavelength 
             then the same model is used for all wavelenths.  
        Returns:
             None
        '''
        self.model_disk = model_disk
        self.model_disks = np.zeros(self.inputs_shape)
        model_disk_shape = np.shape(model_disk)        
        n_disk_wvs = model_disk_shape[0]
        
        #If we do, then let's make sure that the number of wavelenth channels matches the data. 
        nfiles = int(np.nanmax(self.dataset.filenums))+1 #Get the number of files  
        n_wv_per_file = int(self.inputs_shape[0]/nfiles) #Number of wavelenths per file. 
        

        # Check if we have a disk at multiple wavelengths
        if np.size(model_disk_shape) > 2: #Then it's a spec mode disk

            if n_disk_wvs != n_wv_per_file: 
                #The model wvs does notmatch the number of dataset wvs
                # we just use the first model in the cube and repeat

                print("The number of wavelenths in your data don't match the number of wavelenths in your disk model.")
                print("Using the first model in the model disk cube for all wavelenths")
                
                self.model_disk = np.zeros(n_disk_wvs, np.size(model_disk_shape)[1], np.size(model_disk_shape)[2])
                for j,wvs in enumerate(range(n_disk_wvs)):
                    self.model_disk[j] = model_disk[0,:,:]
                model_disk = self.model_disk

            for k in np.arange(nfiles):
                for j,wvs in enumerate(range(n_disk_wvs)):
                    model_copy = copy.deepcopy(model_disk[j,:,:])
                    model_copy = rotate(model_copy, self.pas[k*n_wv_per_file+j], self.aligned_center, flipx = True)
                    model_copy[np.where(np.isnan(model_copy))] = 0.
                    self.model_disks[k*n_wv_per_file+j,:,:] = model_copy 
        
        else: # This is a 2D disk model (no wavelength here)

            for i, pa in enumerate(self.pas):
                model_copy = copy.deepcopy(model_disk)
                model_copy = rotate(model_copy, pa, self.aligned_center, flipx = True)
                model_copy[np.where(np.isnan(model_copy))] = 0.
                self.model_disks[i] = model_copy
        
        self.model_disks = np.reshape(self.model_disks, (self.inputs_shape[0], self.inputs_shape[1] * self.inputs_shape[2])) 

    def _save_rotated_section(self, input_shape, sector, sector_ind, output_img, output_img_numstacked, 
                                    angle, radstart, radend, phistart, phiend, padding,IOWA, img_center, 
                                    flipx=True, new_center=None):
        """
        Rotate and save sector in output image at desired ranges
        This is almost copy past from fm.py
        Need another version of this for load_image because global variables made in fm.py won't work in here. 
        FIXME: There is probably another way because fmpsf.py is not redifining this function


        Args:
            input_shape: shape of input_image
            sector: data in the sector to save to output_img
            sector_ind: index into input img (corresponding to input_shape) for the original sector
            output_img: the array to save the data to
            output_img_numstacked: array to increment region where we saved output to to bookkeep stacking. None for
                                   skipping bookkeeping
            angle: angle that the sector needs to rotate (I forget the convention right now)

            The next 6 parameters define the sector geometry in input image coordinates
            radstart: radius from img_center of start of sector
            radend: radius from img_center of end of sector
            phistart: azimuthal start of sector
            phiend: azimuthal end of sector
            padding: amount of padding around each sector
            IOWA: tuple (IWA,OWA) where IWA = Inner working angle and OWA = Outer working angle both in pixels.
                    It defines the separation interva in which klip will be run.
            img_center: center of image in input image coordinate
            flipx: if true, flip the x coordinate to switch coordinate handiness
            new_center: if not none, center of output_img. If none, center stays the same
        """
        # convert angle to radians
        angle_rad = np.radians(angle)

        #wrap phi
        phistart %= 2 * np.pi
        phiend %= 2 * np.pi

        #incorporate padding
        IWA,OWA = IOWA
        radstart_padded = np.max([radstart-padding,IWA])
        if OWA is not None:
            radend_padded = np.min([radend+padding,OWA])
        else:
            radend_padded = radend+padding
        phistart_padded = (phistart - padding/np.mean([radstart, radend])) % (2 * np.pi)
        phiend_padded = (phiend + padding/np.mean([radstart, radend])) % (2 * np.pi)

        # create the coordinate system of the image to manipulate for the transform
        dims = input_shape
        x, y = np.meshgrid(np.arange(dims[1], dtype=np.float32), np.arange(dims[0], dtype=np.float32))

        # if necessary, move coordinates to new center
        if new_center is not None:
            dx = new_center[0] - img_center[0]
            dy = new_center[1] - img_center[1]
            x -= dx
            y -= dy

        # flip x if needed to get East left of North
        if flipx is True:
            x = img_center[0] - (x - img_center[0])

        # do rotation. CW rotation formula to get a CCW of the image
        xp = (x-img_center[0])*np.cos(angle_rad) + (y-img_center[1])*np.sin(angle_rad) + img_center[0]
        yp = -(x-img_center[0])*np.sin(angle_rad) + (y-img_center[1])*np.cos(angle_rad) + img_center[1]

        if new_center is None:
            new_center = img_center

        rot_sector_pix = fm._get_section_indicies(input_shape, new_center, radstart, radend, phistart, phiend,
                                            padding, 0, IOWA, flatten=False, flipx=flipx)


        # do NaN detection by defining any pixel in the new coordiante system (xp, yp) as a nan
        # if any one of the neighboring pixels in the original image is a nan
        # e.g. (xp, yp) = (120.1, 200.1) is nan if either (120, 200), (121, 200), (120, 201), (121, 201)
        # is a nan
        dims = input_shape
        blank_input = np.zeros(dims[1] * dims[0])
        blank_input[sector_ind] = sector
        blank_input.shape = [dims[0], dims[1]]

        xp_floor = np.clip(np.floor(xp).astype(int), 0, xp.shape[1]-1)[rot_sector_pix]
        xp_ceil = np.clip(np.ceil(xp).astype(int), 0, xp.shape[1]-1)[rot_sector_pix]
        yp_floor = np.clip(np.floor(yp).astype(int), 0, yp.shape[0]-1)[rot_sector_pix]
        yp_ceil = np.clip(np.ceil(yp).astype(int), 0, yp.shape[0]-1)[rot_sector_pix]
        rotnans = np.where(np.isnan(blank_input[yp_floor.ravel(), xp_floor.ravel()]) | 
                        np.isnan(blank_input[yp_floor.ravel(), xp_ceil.ravel()]) |
                        np.isnan(blank_input[yp_ceil.ravel(), xp_floor.ravel()]) |
                        np.isnan(blank_input[yp_ceil.ravel(), xp_ceil.ravel()]))

        # resample image based on new coordinates, set nan values as median
        nanpix = np.where(np.isnan(blank_input))
        medval = np.median(blank_input[np.where(~np.isnan(blank_input))])
        input_copy = np.copy(blank_input)
        input_copy[nanpix] = medval
        rot_sector = ndimage.map_coordinates(input_copy, [yp[rot_sector_pix], xp[rot_sector_pix]], cval=np.nan)

        # mask nans
        rot_sector[rotnans] = np.nan
        sector_validpix = np.where(~np.isnan(rot_sector))

        # need to define only where the non nan pixels are, so we can store those in the output image
        blank_output = np.zeros([dims[0], dims[1]]) * np.nan
        blank_output[rot_sector_pix] = rot_sector
        blank_output.shape = (dims[0], dims[1])
        rot_sector_validpix_2d = np.where(~np.isnan(blank_output))

        # save output sector. We need to reshape the array into 2d arrays to save it
        output_img.shape = [self.outputs_shape[1], self.outputs_shape[2]]
        output_img[rot_sector_validpix_2d] = np.nansum([output_img[rot_sector_pix][sector_validpix], rot_sector[sector_validpix]], axis=0)
        output_img.shape = [self.outputs_shape[1] * self.outputs_shape[2]]

        # Increment the numstack counter if it is not None
        if output_img_numstacked is not None:
            output_img_numstacked.shape = [self.outputs_shape[1], self.outputs_shape[2]]
            output_img_numstacked[rot_sector_validpix_2d] += 1
            output_img_numstacked.shape = [self.outputs_shape[1] *  self.outputs_shape[2]]
