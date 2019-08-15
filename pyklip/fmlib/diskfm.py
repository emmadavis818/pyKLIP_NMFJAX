from sys import version_info
from os import path
import multiprocessing as mp
from copy import deepcopy
import ctypes

import pickle
import deepdish.io as ddh5

import numpy as np

from pyklip.fmlib.nofm import NoFM
import pyklip.fm as fm
from pyklip.klip import rotate


# define the global variables for that code
parallel = True

# Set up global multi-processing dictionaries for saving FM basis
manager = mp.Manager()
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

klparam_dict = manager.dict()


class DiskFM(NoFM):
    """
    Forward modelling class for disks through KLIP. Returns the forward modelled disk.
    """

    def __init__(self,
                 inputs_shape,
                 numbasis,
                 dataset,
                 model_disk,
                 basis_filename="klip-basis.h5",
                 load_from_basis=False,
                 save_basis=False,
                 aligned_center=None,
                 numthreads=None,
                 annuli=None,
                 subsections=None,
                 mode=None):
        """
        Defining a model disk at which we will apply the Forward modelling. There are 3
        ways:
            - "Save Basis mode" (save_basis = true), we are preparing to save the FM
                basis
            - "Load Basis mode" (load_from_basis = true), most of the parameters are
                derived from the previous fm.klip_dataset which measured FM basis. If
                load_from_basis is True, save_basis is automatically set to False, it is
                useless to load and save the matrix at the same time.
            - "Simple FM mode" (save_basis = load_from_basis = False). We juste use it
                for a unique disk FM.

        Args:
            inputs_shape:   shape of the inputs numpy array. Typically (N, x, y)
            numbasis:       1d numpy array consisting of the number of basis vectors to
                            use
            dataset:        an instance of Instrument.Data. We need it to know the
                            parameters to "prepare" first inital model.
            model_disk      a model of the disk of size (wvs, x, y) or (x, y)
            basis_filename  filename to save and load the KL basis. Filenames can haves
                            2 recognizable extensions: .h5 or .pkl. We strongly
                            recommand .h5 as pickle have problem of compatibility
                            between python 2 and 3 and sometimes between computer
                            (e.g. KL modes not readable on another computer)
            load_from_basis if True, load the KL basis at basis_filename. It only need
                            to be done once, after which you can measure FM with
                            only update_model()
            save_basis      if True, save the KL basis at basis_filename. If
                            load_from_basis is True, save_basis is automatically set to
                            False, it is useless to load and save the matrix at the same
                            time.
            numthreads      number of threads to use. If none, defaults to using all
                            the cores of the cpu
            aligned_center  array of 2 elements [x,y] that all the model will be
                            centered on for image registration.
                            FIXME: This is the most problematic thing currently, the
                            aligned_center of the model and of the images can be set
                            independently, which will create false results.
                            - In "Load Basis mode", this parameter is not read, we just
                            use the aligned_center set for the images in the previous
                            fm.klip_dataset and save in basis_filename
                            - In "Save Basis mode", or "Simple FM mode" we define it
                            and then check that it is the same one used for the images
                            in fm.klip_dataset


            There are also 3 deprecated parameters that are ignored and replaced by the
            klip param in fm.klip_dataset:
            annuli
            subsections
            mode
            I let them here for now to avoid breaking the current users' code.

        """

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
        self.inputs_shape = inputs_shape
        self.numbasis = numbasis
        self.numims = inputs_shape[0]

        # Input dataset attributes
        # self.images = dataset.input
        self.PAs = dataset.PAs
        self.wvs = dataset.wvs
        self.nfiles = int(np.nanmax(dataset.filenums)) + \
            1  # Get the number of files

        # Outputs attributes
        output_imgs_shape = dataset.input.shape + self.numbasis.shape
        self.output_imgs_shape = output_imgs_shape
        self.outputs_shape = output_imgs_shape

        self.data_type = ctypes.c_float

        self.basis_filename = basis_filename

        self.save_basis = save_basis
        self.load_from_basis = load_from_basis

        if self.load_from_basis:
            # Its useless to save and load at the same time.
            self.save_basis = False
            save_basis = False

        if numthreads is None:
            self.numthreads = mp.cpu_count()
        else:
            self.numthreads = numthreads

        # Coords where align_and_scale places model center
        # default aligned_center if none:
        if aligned_center is None:
            aligned_center = [
                int(dataset.input.shape[2] // 2),
                int(dataset.input.shape[1] // 2),
            ]
            # aligned_center = [
            #     np.mean(dataset.centers[:, 0]),
            #     np.mean(dataset.centers[:, 1]),
            # ]
            # FIXME I put the one that was by defaut in previous version for continuity.
            # But this is not the one set by default in fm.klip_dataset so I need to
            # change it.
            # This is not ideal, but this is how fm.klip_dataset is set by defaut so we
            # should have the same defaut

        if self.load_from_basis is True:  # We want to load the FM basis
            self.load_basis_files(dataset)
            # We load the FM basis files, before preparing the model to be sure the
            # parameters (IWA, OWA, aligned_center) are identical to the one used used
            # on the data when measuring the KL

        else:  # We want to save the basis or just a single disk FM
            # define the center
            self.aligned_center = aligned_center

        # Prepare the first disk for FM
        self.update_disk(model_disk)

    def update_disk(self, model_disk):
        """
        Takes model disk and rotates it to the PAs of the input images for use as
        reference PSFS

        The disk can be either an 3D array of shape (wvs,y,x) for data of the same shape
        or a 2D Array of shape (y,x), in which case, if the dataset is multiwavelength
        the same model is used for all wavelenths.

        Args:
            model_disk: Disk to be forward modeled.
        Returns:
            None
        """

        self.model_disks = np.zeros(self.inputs_shape)

        # Extract the # of WL per files
        n_wv_per_file = int(
            self.inputs_shape[0] // self.nfiles
        )  # Number of wavelenths per file.

        model_disk_shape = np.shape(model_disk)

        if (np.size(model_disk_shape) == 2) & (n_wv_per_file > 1):
            # This is a single WL 2D model in a multi-wl 3D data,
            # in that case we repeat this model at each WL
            self.model_disk = np.broadcast_to(
                model_disk, (n_wv_per_file,) + model_disk.shape
            )
            model_disk_shape = np.shape(model_disk)
        else:
            # This is either a multi WL 3D model in a multi-wl 3D data
            # or a single WL 3D model in a single-wl 2D data, we do nothing
            self.model_disk = model_disk

        # Check if we have a disk at multiple wavelengths
        if np.size(model_disk_shape) > 2:  # Then it's a multiWL model
            n_model_wvs = model_disk_shape[0]

            if n_model_wvs != n_wv_per_file:
                # Both models and data are multiWL, but not the same number of WLs !
                raise ValueError(
                    """Number of wls in disk model ({0}) don't match number of wls in
                    the data ({1})""".format(n_model_wvs, n_wv_per_file)
                )

            for k in np.arange(self.nfiles):
                for j, _ in enumerate(range(n_model_wvs)):
                    model_copy = deepcopy(model_disk[j, :, :])
                    model_copy = rotate(
                        model_copy,
                        self.PAs[k * n_wv_per_file + j],
                        self.aligned_center,
                        flipx=True,
                    )
                    model_copy[np.where(np.isnan(model_copy))] = 0.0
                    self.model_disks[k * n_wv_per_file + j, :, :] = model_copy

        else:  # This is a 2D disk model and a wl = 1 case

            for i, pa_here in enumerate(self.PAs):
                model_copy = deepcopy(model_disk)
                model_copy = rotate(
                    model_copy, pa_here, self.aligned_center, flipx=True
                )
                model_copy[np.where(np.isnan(model_copy))] = 0.0
                self.model_disks[i] = model_copy

        self.model_disks = np.reshape(
            self.model_disks,
            (self.inputs_shape[0], self.inputs_shape[1]
             * self.inputs_shape[2]),
        )

    def alloc_fmout(self, output_img_shape):
        """Allocates shared memory for the output of the shared memory


        Args:
            output_img_shape: shape of output image (usually N,y,x,b)

        Returns:
            fmout: mp.array to store FM data in
            fmout_shape: shape of FM data array

        """

        fmout_size = int(np.prod(output_img_shape))
        fmout_shape = output_img_shape
        fmout = mp.Array(self.data_type, fmout_size)
        return fmout, fmout_shape

    def fm_from_eigen(self,
                      klmodes=None,
                      evals=None,
                      evecs=None,
                      input_img_shape=None,
                      input_img_num=None,
                      ref_psfs_indicies=None,
                      section_ind=None,
                      aligned_imgs=None,
                      radstart=None,
                      radend=None,
                      phistart=None,
                      phiend=None,
                      padding=None,
                      IOWA=None,
                      ref_center=None,
                      parang=None,
                      numbasis=None,
                      fmout=None,
                      flipx=True,
                      **kwargs):
        """
        Generate forward models using the KL modes, eigenvectors, and eigenvectors from
        KLIP. Calls fm.py functions to perform the forward modelling. If we wish to save
        the KL modes, it save in dictionnaries.

        Args:
            klmodes: unpertrubed KL modes
            evals: eigenvalues of the covariance matrix that generated the KL modes in
                    ascending order(lambda_0 is the 0 index) (shape of [nummaxKL])
            evecs: corresponding eigenvectors (shape of [p, nummaxKL])
            input_image_shape: 2-D shape of inpt images ([ysize, xsize])
            input_img_num: index of sciece frame
            ref_psfs_indicies: array of indicies for each reference PSF
            section_ind: array indicies into the 2-D x-y image that correspond to
                            this section. Note: needs be called as section_ind[0]
            radstart: radius of start of segment
            radend: radius of end of segment
            phistart: azimuthal start of segment [radians]
            phiend: azimuthal end of segment [radians]
            padding: amount of padding on each side of sector
            IOWA: tuple (IWA,OWA) IWA = Inner working angle & OWA = Outer working angle,
                    both in pixels. It defines the separation interva in which klip will
                    be run.
            ref_center: center of image
            parang: parallactic angle of input image [DEGREES]
            numbasis: array of KL basis cutoffs
            fmout: numpy output array for FM output. Shape is (N, y, x, b)
            kwargs: any other variables that we don't use but are part of the input
        """

        # we check that the aligned_center used to center the disk (self.aligned_center)
        # If the same used to center the image in klip_dataset.
        # If not, we should not continue.

        if self.aligned_center != ref_center:
            err_string = """The aligned_center for the model {0} and for
                            the data {1} is different.
                            Change and rerun""".format(self.aligned_center, ref_center)

            print(err_string)
            raise ValueError(err_string)
            # FIXME I cannot raised that error because multiproc
            # or use in different class so I just print it in case it happens

        sci = aligned_imgs[input_img_num, section_ind[0]]
        refs = aligned_imgs[ref_psfs_indicies, :]
        refs = refs[:, section_ind[0]]
        refs[np.where(np.isnan(refs))] = 0

        # use the disk model stored
        model_sci = self.model_disks[input_img_num, section_ind[0]]
        model_ref = self.model_disks[ref_psfs_indicies, :]
        model_ref = model_ref[:, section_ind[0]]
        model_ref[np.where(np.isnan(model_ref))] = 0

        # using original Kl modes and reference models, compute the perturbed KL modes
        # (spectra is already in models)
        delta_KL = fm.perturb_specIncluded(
            evals, evecs, klmodes, refs, model_ref, return_perturb_covar=False
        )

        # calculate postklip_psf using delta_KL
        postklip_psf, _, _ = fm.calculate_fm(
            delta_KL, klmodes, numbasis, sci, model_sci, inputflux=None
        )

        # write forward modelled disk to fmout (as output)
        # need to derotate the image in this step
        for thisnumbasisindex in range(np.size(numbasis)):
            fm._save_rotated_section(
                input_img_shape,
                postklip_psf[thisnumbasisindex],
                section_ind,
                fmout[input_img_num, :, :, thisnumbasisindex],
                None,
                parang,
                radstart,
                radend,
                phistart,
                phiend,
                padding,
                IOWA,
                ref_center,
                flipx=flipx,
            )

        # We save the KL basis and params for this image and section in a dictionnaries
        if self.save_basis is True:
            # save the parameter used in KLIP-FM
            [IWA, OWA] = IOWA
            klparam_dict["IWA"] = IWA
            klparam_dict["OWA"] = OWA
            klparam_dict["aligned_center"] = ref_center
            # save the center for aligning the image in KLIP-FM. In practice, this
            # center will be used for all the models after we load.

            curr_im = str(input_img_num)
            if len(curr_im) < 3:
                curr_im = "00" + curr_im

            # To have a single identifier for each set of section/image for the
            # dictionnaries key, we use section first pixel and image number
            namkey = "idsec" + str(section_ind[0][0]) + "i" + curr_im
            # saving the KL modes dictionnaries
            klmodes_dict[namkey] = klmodes
            evals_dict[namkey] = evals
            evecs_dict[namkey] = evecs
            ref_psfs_indicies_dict[namkey] = ref_psfs_indicies
            section_ind_dict[namkey] = section_ind

            # saving the section delimiters dictionnaries
            radstart_dict[namkey] = radstart
            radend_dict[namkey] = radend
            phistart_dict[namkey] = phistart
            phiend_dict[namkey] = phiend
            input_img_num_dict[namkey] = input_img_num

    def cleanup_fmout(self, fmout):
        """
        After running KLIP-FM, we need to reshape fmout so that the numKL dimension is
        the first one and not the last. We also use this function to save the KL basis
        because it is called by fm.py at the end fm.klip_parallelized
        Args:
            fmout: numpy array of ouput of FM

        Returns:
            fmout: same but cleaned up if necessary
        """

        # save the KL basis.
        if self.save_basis:
            self.save_kl_basis()

        # FIXME We save the matrix here it here because it is called by fm.py at the end
        # fm.klip_parallelized but this is not ideal.

        dims = fmout.shape
        fmout = np.rollaxis(fmout.reshape(
            (dims[0], dims[1], dims[2], dims[3])), 3)
        return fmout

    def save_fmout(self,
                   dataset,
                   fmout,
                   outputdir,
                   fileprefix,
                   numbasis,
                   klipparams=None,
                   calibrate_flux=False,
                   pixel_weights=1,
                   **kwargs):
        """
        Uses dataset parameters to save the forward model, the output of
        fm_paralellized or klip_dataset.

        Arg:
            dataset:        an instance of Instrument.Data . Will use its
                            dataset.savedata() function to save data
            fmout:          output of forward modelling.
            outputdir:      directory to save output files
            fileprefix:     filename prefix for saved files
            numbasis:       number of KL basis vectors to use
                            (can be a scalar or list like)
            klipparams:     string with KLIP-FM parameters
            calibrate_flux: if True, flux calibrate the data in the same way as
                            the klipped data
            pixel_weights:  weights for each pixel for weighted mean. Leave this as a
                            single number for simple mean

        """

        weighted = len(np.shape(pixel_weights)) > 1
        numwvs = dataset.numwvs
        fmout_spec = fmout.reshape(
            [
                fmout.shape[0],
                fmout.shape[1] // numwvs,
                numwvs,
                fmout.shape[2],
                fmout.shape[3],
            ]
        )  # (b, N_cube, wvs, y, x) 5-D cube

        # collapse in time and wavelength to examine KL modes
        KLmode_cube = np.nanmean(pixel_weights * fmout_spec, axis=(1, 2))
        if weighted:
            # if the pixel weights aren't just 1 (i.e., weighted case),
            # we need to normalize for that
            KLmode_cube /= np.nanmean(pixel_weights, axis=(1, 2))

        # broadband flux calibration for KL mode cube
        if calibrate_flux:
            KLmode_cube = dataset.calibrate_output(KLmode_cube, spectral=False)
        dataset.savedata(
            outputdir + "/" + fileprefix + "-fmpsf-KLmodes-all.fits",
            KLmode_cube,
            klipparams=klipparams.format(numbasis=str(numbasis)),
            filetype="KL Mode Cube",
            zaxis=numbasis,
        )

        # if there is more than one wavelength, save also spectral cubes
        if dataset.numwvs > 1:

            KLmode_spectral_cubes = np.nanmean(
                pixel_weights * fmout_spec, axis=1)
            if weighted:
                # if the pixel weights aren't just 1 (i.e., weighted case), we need to
                # normalize for that.
                KLmode_spectral_cubes /= np.nanmean(pixel_weights, axis=1)

            for KLcutoff, spectral_cube in zip(numbasis, KLmode_spectral_cubes):
                # calibrate spectral cube if needed
                if calibrate_flux:
                    spectral_cube = dataset.calibrate_output(
                        spectral_cube, spectral=True
                    )
                dataset.savedata(
                    outputdir
                    + "/"
                    + fileprefix
                    + "-fmpsf-KL{0}-speccube.fits".format(KLcutoff),
                    spectral_cube,
                    klipparams=klipparams.format(numbasis=KLcutoff),
                    filetype="PSF Subtracted Spectral Cube",
                )

    def save_kl_basis(self):
        """
        Save the KL basis and other needed parameters

        Args:
            None

        Returns:
            None
        """

        _, file_extension = path.splitext(self.basis_filename)
        if file_extension == ".pkl":
            # transform mp dicts to normal dicts
            pickle_file = open(self.basis_filename, "wb")
            pickle.dump(dict(klmodes_dict), pickle_file, protocol=2)
            pickle.dump(dict(evecs_dict), pickle_file, protocol=2)
            pickle.dump(dict(evals_dict), pickle_file, protocol=2)
            pickle.dump(dict(ref_psfs_indicies_dict), pickle_file, protocol=2)
            pickle.dump(dict(section_ind_dict), pickle_file, protocol=2)

            pickle.dump(dict(radstart_dict), pickle_file, protocol=2)
            pickle.dump(dict(radend_dict), pickle_file, protocol=2)
            pickle.dump(dict(phistart_dict), pickle_file, protocol=2)
            pickle.dump(dict(phiend_dict), pickle_file, protocol=2)
            pickle.dump(dict(input_img_num_dict), pickle_file, protocol=2)

            pickle.dump(dict(klparam_dict), pickle_file, protocol=2)

        elif file_extension == ".h5":
            # transform mp dicts to normal dicts
            # make a single dictionnary and save in h5
            dict_for_saving_in_h5 = {
                "klmodes_dict": dict(klmodes_dict),
                "evecs_dict": dict(evecs_dict),
                "evals_dict": dict(evals_dict),
                "ref_psfs_indicies_dict": dict(ref_psfs_indicies_dict),
                "section_ind_dict": dict(section_ind_dict),
                "radstart_dict": dict(radstart_dict),
                "radend_dict": dict(radend_dict),
                "phistart_dict": dict(phistart_dict),
                "phiend_dict": dict(phiend_dict),
                "input_img_num_dict": dict(input_img_num_dict),
                "klparam_dict": dict(klparam_dict),
            }
            ddh5.save(self.basis_filename, dict_for_saving_in_h5)
            del dict_for_saving_in_h5

        else:
            raise ValueError(
                file_extension + """ is not a possible extension. Filenames can
                haves 2 recognizable extension: .h5 or .pkl"""
            )

    def load_basis_files(self, dataset):
        """
        Loads in previously saved basis files and sets variables for fm_from_eigen

        Args:
            dataset:        an instance of Instrument.Data, after fm.klip_dataset.
                            Allow me to pass in the structure some correction parameters
                            set by fm.klip_dataset, such as IWA, OWA, aligned_center

        Return: None
        """
        _, file_extension = path.splitext(self.basis_filename)

        # Load in file
        if file_extension == ".pkl":
            pickle_file = open(self.basis_filename, "rb")
            if version_info.major == 3:
                self.klmodes_dict = pickle.load(pickle_file, encoding="latin1")
                self.evecs_dict = pickle.load(pickle_file, encoding="latin1")
                self.evals_dict = pickle.load(pickle_file, encoding="latin1")
                self.ref_psfs_indicies_dict = pickle.load(
                    pickle_file, encoding="latin1"
                )
                self.section_ind_dict = pickle.load(
                    pickle_file, encoding="latin1")

                self.radstart_dict = pickle.load(
                    pickle_file, encoding="latin1")
                self.radend_dict = pickle.load(pickle_file, encoding="latin1")
                self.phistart_dict = pickle.load(
                    pickle_file, encoding="latin1")
                self.phiend_dict = pickle.load(pickle_file, encoding="latin1")
                self.input_img_num_dict = pickle.load(
                    pickle_file, encoding="latin1")

                self.klparam_dict = pickle.load(pickle_file, encoding="latin1")

            else:
                self.klmodes_dict = pickle.load(pickle_file)
                self.evecs_dict = pickle.load(pickle_file)
                self.evals_dict = pickle.load(pickle_file)
                self.ref_psfs_indicies_dict = pickle.load(pickle_file)
                self.section_ind_dict = pickle.load(pickle_file)

                self.radstart_dict = pickle.load(pickle_file)
                self.radend_dict = pickle.load(pickle_file)
                self.phistart_dict = pickle.load(pickle_file)
                self.phiend_dict = pickle.load(pickle_file)
                self.input_img_num_dict = pickle.load(pickle_file)

                self.klparam_dict = pickle.load(pickle_file)

        if file_extension == ".h5":
            dict_for_saving_in_h5 = ddh5.load(self.basis_filename)

            self.klmodes_dict = dict_for_saving_in_h5["klmodes_dict"]
            self.evecs_dict = dict_for_saving_in_h5["evecs_dict"]
            self.evals_dict = dict_for_saving_in_h5["evals_dict"]
            self.ref_psfs_indicies_dict = dict_for_saving_in_h5[
                "ref_psfs_indicies_dict"
            ]
            self.section_ind_dict = dict_for_saving_in_h5["section_ind_dict"]

            self.radstart_dict = dict_for_saving_in_h5["radstart_dict"]
            self.radend_dict = dict_for_saving_in_h5["radend_dict"]
            self.phistart_dict = dict_for_saving_in_h5["phistart_dict"]
            self.phiend_dict = dict_for_saving_in_h5["phiend_dict"]
            self.input_img_num_dict = dict_for_saving_in_h5["input_img_num_dict"]

            self.klparam_dict = dict_for_saving_in_h5["klparam_dict"]

            del dict_for_saving_in_h5

        # read key name for each section and image
        self.dict_keys = sorted(self.klmodes_dict.keys())

        # load parameters of the correction that fm.klip_dataset produced
        # when we saved the FM basis.
        self.IWA = self.klparam_dict["IWA"]
        self.OWA = self.klparam_dict["OWA"]

        # all output images have the same center, to which we shoudl aligned our models
        self.aligned_center = self.klparam_dict["aligned_center"]
        # dataset.output_centers[0]

        numthreads = self.numthreads

        # implement the thread pool
        # # make a bunch of shared memory arrays to transfer data between threads
        # # make the array for the original images and initalize it
        original_imgs = mp.Array(self.data_type, np.size(dataset.input))
        original_imgs_shape = dataset.input.shape
        original_imgs_np = fm._arraytonumpy(
            original_imgs, original_imgs_shape, dtype=self.data_type
        )
        original_imgs_np[:] = dataset.input
        # make array for recentered/rescaled image for each wavelength
        unique_wvs = np.unique(self.wvs)
        recentered_imgs = mp.Array(
            self.data_type, np.size(dataset.input) * np.size(unique_wvs)
        )
        recentered_imgs_shape = (np.size(unique_wvs),) + dataset.input.shape

        # remake the PA, wv, and center arrays as shared arrays
        pa_imgs = mp.Array(self.data_type, np.size(self.PAs))
        pa_imgs_np = fm._arraytonumpy(pa_imgs, dtype=self.data_type)
        pa_imgs_np[:] = self.PAs
        wvs_imgs = mp.Array(self.data_type, np.size(self.wvs))
        wvs_imgs_np = fm._arraytonumpy(wvs_imgs, dtype=self.data_type)
        wvs_imgs_np[:] = self.wvs
        centers_imgs = mp.Array(self.data_type, np.size(dataset.centers))
        centers_imgs_np = fm._arraytonumpy(
            centers_imgs, dataset.centers.shape, dtype=self.data_type
        )
        centers_imgs_np[:] = dataset.centers

        # we will not save the fits fm_in parallelize, so we don't need those
        output_imgs = None
        output_imgs_numstacked = None

        output_imgs_shape = dataset.input.shape + self.numbasis.shape
        self.output_imgs_shape = output_imgs_shape
        self.outputs_shape = output_imgs_shape

        # Create Custom Shared Memory array fmout to save output of forward modelling
        fmout_data, fmout_shape = self.alloc_fmout(self.output_imgs_shape)

        # align and scale the images for each image. Use map to do this asynchronously

        # I need to run this code at least once in non-parallel mode to initialize the
        # global variable outputs_shape in fm.py, because if I don't I cannot use
        # fm._save_rotated_section. This is a short stuff and we do it only once.
        fm._tpool_init(original_imgs,
                       original_imgs_shape,
                       recentered_imgs,
                       recentered_imgs_shape,
                       output_imgs,
                       self.output_imgs_shape,
                       output_imgs_numstacked,
                       pa_imgs,
                       wvs_imgs,
                       centers_imgs,
                       None,
                       None,
                       fmout_data,
                       fmout_shape,
                       None,
                       None)

        tpool = mp.Pool(processes=numthreads,
                        initializer=fm._tpool_init,
                        initargs=(original_imgs,
                                  original_imgs_shape,
                                  recentered_imgs,
                                  recentered_imgs_shape,
                                  output_imgs,
                                  self.output_imgs_shape,
                                  output_imgs_numstacked,
                                  pa_imgs,
                                  wvs_imgs,
                                  centers_imgs,
                                  None,
                                  None,
                                  fmout_data,
                                  fmout_shape,
                                  None,
                                  None),
                        maxtasksperchild=50)

        print("Begin align and scale images for each wavelength")
        aligned_outputs = []
        for threadnum in range(self.numthreads):
            aligned_outputs += [
                tpool.apply_async(
                    fm._align_and_scale_subset,
                    args=(
                        threadnum,
                        self.aligned_center,
                        self.numthreads,
                        self.data_type,
                    ),
                )
            ]
            # save it to shared memory
        for aligned_output in aligned_outputs:
            aligned_output.wait()

        self.aligned_imgs_np = fm._arraytonumpy(
            recentered_imgs,
            shape=(
                recentered_imgs_shape[0],
                recentered_imgs_shape[1],
                recentered_imgs_shape[2] * recentered_imgs_shape[3],
            ),
        )
        self.wvs_imgs_np = wvs_imgs_np
        self.pa_imgs_np = pa_imgs_np

        # After loading it, we stop saving the KL basis to avoid saving it every time
        # we run self.fm_parallelize.
        self.save_basis = False

    def fm_parallelized(self):
        """
        Functions like fm.klip_dataset, but it uses previously measured KL modes,
        section positions, and klip parameter to return the forward modelling.
        Do not save fits.

        Args:
        None

        Return:
        fmout_np:   output of forward modelling of size [n_KL,N_wl,x,y] if N_wl>1
                    and [n_KL,x,y] if not

        """

        fmout_data, fmout_shape = self.alloc_fmout(self.output_imgs_shape)
        fmout_np = fm._arraytonumpy(
            fmout_data, fmout_shape, dtype=self.data_type)

        wvs = self.wvs
        unique_wvs = np.unique(wvs)
        original_imgs_shape = self.inputs_shape

        for key in self.dict_keys:  # loop pver the sections/images
            # load KL from the dictionnaries
            original_KL = self.klmodes_dict[key]
            evals = self.evals_dict[key]
            evecs = self.evecs_dict[key]
            ref_psfs_indicies = self.ref_psfs_indicies_dict[key]
            section_ind = self.section_ind_dict[key]

            # load zone information from the KL
            radstart = self.radstart_dict[key]
            radend = self.radend_dict[key]
            phistart = self.phistart_dict[key]
            phiend = self.phiend_dict[key]
            img_num = self.input_img_num_dict[key]

            # # We can also re-measure the section at every run of fm_parallelized.
            # # This is the only "dictionnary array" that is big and fast to measure at
            # # the same time so it can be done if RAM is a pb (the dict variables
            # # are going to put in global in the MCMC). I put the code here if wanted:

            # section_ind = fm._get_section_indicies(
            #     self.inputs_shape[1:],
            #     self.aligned_center,
            #     radstart,
            #     radend,
            #     phistart,
            #     phiend,
            #     0.0,
            #     self.pa_imgs_np[img_num],
            #     (self.IWA, self.OWA),
            #     flatten=True,
            #     flipx=False,
            # )

            wl_here = wvs[img_num]
            wv_index = (np.where(unique_wvs == wl_here))[0][0]
            aligned_imgs_for_this_wl = self.aligned_imgs_np[wv_index]

            self.fm_from_eigen(klmodes=original_KL,
                               evals=evals,
                               evecs=evecs,
                               input_img_shape=[original_imgs_shape[1],
                                                original_imgs_shape[2]],
                               input_img_num=img_num,
                               ref_psfs_indicies=ref_psfs_indicies,
                               section_ind=section_ind,
                               aligned_imgs=aligned_imgs_for_this_wl,
                               radstart=radstart,
                               radend=radend,
                               phistart=phistart,
                               phiend=phiend,
                               padding=0.0,
                               IOWA=(self.IWA, self.OWA),
                               ref_center=self.aligned_center,
                               parang=self.pa_imgs_np[img_num],
                               numbasis=self.numbasis,
                               fmout=fmout_np)

        # put any finishing touches on the FM Output
        fmout_np = fm._arraytonumpy(
            fmout_data, fmout_shape, dtype=self.data_type)
        fmout_np = self.cleanup_fmout(fmout_np)

        # Check if we have a disk model at multiple wavelengths.
        # If true then it's a non- collapsed spec mode disk and we need to reorganise
        # fmout_return. We use the same mean so that it corresponds to
        # klip image-speccube.fits produced by.fm.klip_dataset
        if np.size(np.shape(self.model_disk)) > 2:

            n_wv_per_file = int(
                self.inputs_shape[0] // self.nfiles
            )  # Number of WL per file.

            # Collapse across all files, keeping the wavelengths intact.
            fmout_return = np.zeros(
                [
                    np.size(self.numbasis),
                    n_wv_per_file,
                    self.inputs_shape[1],
                    self.inputs_shape[2],
                ]
            )
            for i in np.arange(n_wv_per_file):
                fmout_return[:, i, :, :] = (
                    np.nansum(fmout_np[:, i::n_wv_per_file, :, :], axis=1)
                    / float(self.nfiles)
                )

        else:
            # If false then this is a collapsed-spec mode or pol mode: collapsed
            # across all files
            fmout_return = np.nanmean(fmout_np, axis=1)

        return fmout_return
