__author__ = 'JB'

import warnings
import itertools

from scipy.optimize import leastsq
from astropy.modeling import models, fitting
from matplotlib import rcParams
from scipy.interpolate import interp1d
from mpl_toolkits.axes_grid1 import host_subplot
import mpl_toolkits.axisartist as AA

from pyklip.kpp_utils import *


def model_expExp(x,a,m,alpha):
    return np.exp(a*np.exp(-np.abs(x-m)/alpha))

def LSQ_model_expExp(x,y,a,m,alpha):
    y_model = model_expExp(x,a,m,alpha)
    return (y-y_model)/y_model

def model_exp(x,m,alpha):
    return np.exp(-alpha*x-m)

def LSQ_model_exp(x,y,m,alpha):
    y_model = model_exp(x,m,alpha)
    return (y-y_model)/np.sqrt(y_model)


def model_gauss1D(x,a,m,sigma):
    return a*np.exp(-0.5/sigma*(x-m)**2)

def LSQ_model_gauss1D(x,y,a,m,sigma):
    y_model = model_gauss1D(x,a,m,sigma)
    return (y-y_model)

def get_pdf_model(data):
    im_std = np.std(data)
    bins = np.arange(np.min(data),np.max(data),im_std/5.)
    im_histo = np.histogram(data, bins=bins)[0]


    N_bins = bins.size-1
    center_bins = 0.5*(bins[0:N_bins]+bins[1:N_bins+1])

    use_gauss = True
    use_exp = False
    if use_gauss:
        g_init = models.Gaussian1D(amplitude=np.max(im_histo), mean=0.0, stddev=im_std)
        fit_g = fitting.LevMarLSQFitter()
        warnings.simplefilter('ignore')
        g = fit_g(g_init, center_bins, im_histo)#, weights=1/im_histo)
        g.stddev = abs(g.stddev)

        right_side_noZeros = np.where((center_bins > (g.mean+2*g.stddev))*(im_histo != 0))
        N_right_bins_noZeros = len(right_side_noZeros[0])
        left_side_noZeros = np.where((center_bins < (g.mean-2*g.stddev))*(im_histo != 0))
        N_left_bins_noZeros = len(left_side_noZeros[0])

        right_side = np.where((center_bins > (g.mean+2*g.stddev)))
        left_side = np.where((center_bins < (g.mean-2*g.stddev)))
    elif use_exp:
        param0_expExp = (np.log(np.max(im_histo)),0.0,np.max(data)/2.)#,a,m,alpha
        LSQ_func = lambda para: LSQ_model_expExp(center_bins, im_histo,para[0],para[1],para[2])
        param_fit_expExp = leastsq(LSQ_func,param0_expExp)
        print(param_fit_expExp)


        right_side_noZeros = np.where((center_bins > (param_fit_expExp[0][1]+param_fit_expExp[0][2]))*( im_histo != 0))
        N_right_bins_noZeros = len(right_side_noZeros[0])
        left_side_noZeros = np.where((center_bins < (param_fit_expExp[0][1]-param_fit_expExp[0][2]))*( im_histo != 0))
        N_left_bins_noZeros = len(left_side_noZeros[0])

        right_side = np.where((center_bins > (param_fit_expExp[0][1]+param_fit_expExp[0][2])))
        left_side = np.where((center_bins < (param_fit_expExp[0][1]-param_fit_expExp[0][2])))

    if 0:
        fig = 1
        plt.figure(fig,figsize=(8,8))
        plt.plot(center_bins,np.array(im_histo,dtype="double"),'bx-', markersize=5,linewidth=3)
        #plt.plot(center_bins,g(center_bins),'g.')
        plt.plot(center_bins,model_expExp(center_bins,np.log(2000),0.0,2000.),'g.')
        plt.plot(center_bins,model_expExp(center_bins,*param_fit_expExp[0]),'b.')
        plt.plot((bins[0:bins.size-1])[right_side_noZeros],(bins[0:bins.size-1])[right_side_noZeros]*0+1,'ro')
        plt.plot((bins[0:bins.size-1])[left_side_noZeros],(bins[0:bins.size-1])[left_side_noZeros]*0+1,'ro')
        #plt.plot(center_bins,model_gauss1D(center_bins,*param_fit_gauss1D[0]),'r--')
        #plt.plot(new_sampling,np.cumsum(pdf_model),'g.')
        plt.xlabel('criterion value', fontsize=20)
        plt.ylabel('Probability of the value', fontsize=20)
        #plt.xlim((-30.* im_std,20.*im_std))
        plt.grid(True)
        ax = plt.gca()
        ax.tick_params(axis='x', labelsize=20)
        ax.tick_params(axis='y', labelsize=20)
        ax.set_yscale('log')
        plt.ylim((10**-5,100000))
        plt.show()

    if N_right_bins_noZeros < 5:
        where_pos_zero = np.where((im_histo == 0) * (center_bins > g.mean))
        if len(where_pos_zero[0]) != 0:
            right_side_noZeros = (range(where_pos_zero[0][0]-5,where_pos_zero[0][0]),)
            right_side = (range(where_pos_zero[0][0]-5,center_bins.size),)
        else:
            right_side_noZeros = (range(center_bins.size-5,center_bins.size),)
            right_side = right_side_noZeros
        N_right_bins_noZeros = 5

    if N_left_bins_noZeros < 5:
        where_neg_zero = np.where((im_histo == 0) * (center_bins < g.mean))
        if len(where_neg_zero[0]) != 0:
            left_side_noZeros = (range(where_neg_zero[0][len(where_neg_zero[0])-1]+1,where_neg_zero[0][len(where_neg_zero[0])-1]+6),)
            left_side = (range(0,where_neg_zero[0][len(where_neg_zero[0])-1]+6),)
        else:
            left_side_noZeros = (range(0,5),)
            left_side = left_side_noZeros
        N_left_bins_noZeros = 5

    #print(left_side,right_side)
    #print(im_histo[left_side],im_histo[right_side])
    #print(right_side_noZeros,left_side_noZeros)
    #print(im_histo[right_side_noZeros],im_histo[left_side_noZeros])



    #print(N_right_bins_noZeros,N_left_bins_noZeros)
    if N_right_bins_noZeros >= 2:
        alpha0 = (np.log(im_histo[right_side_noZeros[0][N_right_bins_noZeros-1]])-np.log(im_histo[right_side_noZeros[0][0]]))/(center_bins[right_side_noZeros[0][0]]-center_bins[right_side_noZeros[0][N_right_bins_noZeros-1]])
        m_alpha0 = -np.log(im_histo[right_side_noZeros[0][0]])-alpha0*center_bins[right_side_noZeros[0][0]]
        param0_rightExp = (m_alpha0,alpha0)

        LSQ_func = lambda para: LSQ_model_exp((bins[0:bins.size-1])[right_side], im_histo[right_side],para[0],para[1])
        param_fit_rightExp = leastsq(LSQ_func,param0_rightExp)
    else:
        param_fit_rightExp = None
    #print(param0_rightExp,param_fit_rightExp)

    if N_left_bins_noZeros >= 2:
        alpha0 = (np.log(im_histo[left_side_noZeros[0][N_left_bins_noZeros-1]])-np.log(im_histo[left_side_noZeros[0][0]]))/(center_bins[left_side_noZeros[0][0]]-center_bins[left_side_noZeros[0][N_left_bins_noZeros-1]])
        m_alpha0 = -np.log(im_histo[left_side_noZeros[0][0]])-alpha0*center_bins[left_side_noZeros[0][0]]
        param0_leftExp = (m_alpha0,alpha0)

        LSQ_func = lambda para: LSQ_model_exp((bins[0:bins.size-1])[left_side], im_histo[left_side],para[0],para[1])
        param_fit_leftExp = leastsq(LSQ_func,param0_leftExp)
    else:
        param_fit_leftExp = None
    #print(param0_leftExp,param_fit_leftExp)


    new_sampling = np.arange(2*np.min(data),4*np.max(data),im_std/100.)

    #pdf_model_gaussian = g(new_sampling)
    pdf_model_gaussian = interp1d(center_bins,np.array(im_histo,dtype="double"),kind = "cubic",bounds_error = False, fill_value=0.0)(new_sampling)


    if use_gauss:
        right_side2 = np.where((new_sampling >= g.mean))
        left_side2 = np.where((new_sampling < g.mean))
    elif use_exp:
        right_side2 = np.where((new_sampling >= param_fit_expExp[0][1]))
        left_side2 = np.where((new_sampling < param_fit_expExp[0][1]))

    #print(g.mean+0.0,g.stddev+0.0)
    pdf_model_exp = np.zeros(new_sampling.size)
    weights = np.zeros(new_sampling.size)
    if param_fit_rightExp is not None:
        pdf_model_exp[right_side2] = model_exp(new_sampling[right_side2],*param_fit_rightExp[0])
        if use_gauss:
            weights[right_side2] = np.tanh((new_sampling[right_side2]-(g.mean+2*g.stddev))/(0.1*g.stddev))
        elif use_exp:
            weights[right_side2] = np.tanh((new_sampling[right_side2]-(param_fit_expExp[0][1]+param_fit_expExp[0][2]))/(0.1*param_fit_expExp[0][2]))
        #plt.plot(np.tanh((new_sampling[right_side2]-(g.mean+2*g.stddev))/(0.1*g.stddev)))
        #plt.show()
    else:
        weights[right_side2] = -1.

    if param_fit_leftExp is not None:
        pdf_model_exp[left_side2] = model_exp(new_sampling[left_side2],*param_fit_leftExp[0])
        if use_gauss:
            weights[left_side2] = np.tanh(-(new_sampling[left_side2]-(g.mean-2*g.stddev))/(0.1*g.stddev))
        elif use_exp:
            weights[left_side2] = np.tanh(-(new_sampling[right_side2]-(param_fit_expExp[0][1]-param_fit_expExp[0][2]))/(0.1*param_fit_expExp[0][2]))
    else:
        weights[left_side2] = -1.

    '''
        right_side2 = np.where((new_sampling > (g.mean+2*g.stddev)))
        left_side2 = np.where((new_sampling < (g.mean-2*g.stddev)))
        pdf_model_exp = np.zeros(new_sampling.size)
        weights = np.zeros(new_sampling.size)
        if param_fit_rightExp is not None:
            pdf_model_exp[right_side2] = model_exp(new_sampling[right_side2],*param_fit_rightExp[0])
            weights[right_side2] = 1.
        else:
            weights[right_side2] = -1.

        if param_fit_leftExp is not None:
            pdf_model_exp[left_side2] = model_exp(new_sampling[left_side2],*param_fit_leftExp[0])
            weights[right_side2] = 1.
        else:
            weights[left_side2] = -1.
    '''

    weights = 0.5*(weights+1.0)

    #weights[np.where(weights > 1-10^-3)] = 1


    pdf_model = weights*pdf_model_exp + (1-weights)*pdf_model_gaussian
    #pdf_model[np.where(weights > 1-10^-5)] = pdf_model_exp[np.where(pdf_model > 1-10^-5)]

    if 0:
        fig = 2
        plt.figure(fig,figsize=(8,8))
        plt.plot(new_sampling, weights, "r")
        #plt.plot(new_sampling, (1-weights), "--r")
        #plt.plot(new_sampling, pdf_model_exp, "g")
        #plt.plot(new_sampling, pdf_model_gaussian, "b")
        #plt.plot(new_sampling, pdf_model, "c") #/np.sum(pdf_model)
        #plt.plot(new_sampling, 1-np.cumsum(pdf_model/np.sum(pdf_model)), "--.")
        ax = plt.gca()
        #ax.set_yscale('log')
        plt.grid(True)
        #plt.ylim((10**-15,100000))
        #plt.xlim((1*np.min(data),2*np.max(data)))
        plt.show()

    if 0:
        rcParams.update({'font.size': 20})
        fig = 2
        plt.close(2)
        plt.figure(fig,figsize=(16,8))
        plt.subplot(121)
        plt.plot(new_sampling,pdf_model,'r-',linewidth=5)
        if use_gauss:
            plt.plot(center_bins,g(center_bins),'c--',linewidth=3)
        elif use_exp:
            plt.plot(center_bins,model_expExp(center_bins,*param_fit_expExp[0]),'c-')
        plt.plot(new_sampling,pdf_model_exp,'g--',linewidth=3)
        plt.plot(center_bins,np.array(im_histo,dtype="double"),'b.', markersize=10,linewidth=3)
        #plt.plot(new_sampling,np.cumsum(pdf_model),'g.')
        plt.xlabel('Metric value')
        plt.ylabel('Number per bin')
        plt.xlim((2*np.min(data),2*np.max(data)))
        plt.grid(True)
        plt.ticklabel_format(style='sci', axis='x', scilimits=(0,0))
        ax = plt.gca()
        ax.tick_params(axis='x')
        ax.tick_params(axis='y')
        ax.legend(['PDF Model Fit','Central Gaussian Fit','Tails Exponential Fit','Histogram'], loc = 'upper right', fontsize=15)
        ax.set_yscale('log')
        plt.ylim((10**-1,10000))

    pdf_model /= np.sum(pdf_model)

    if 0:
        host = host_subplot(122, axes_class=AA.Axes)
        par1 = host.twinx()
        p1, = host.plot(new_sampling,pdf_model/(new_sampling[1]-new_sampling[0]),'r-',linewidth=5)
        host.tick_params(axis='x', labelsize=20)
        host.tick_params(axis='y', labelsize=20)
        host.set_ylim((10**-3,10**2))
        host.set_yscale('log')
        p2, = par1.plot(new_sampling,1-np.cumsum(pdf_model),'g-',linewidth=5)
        par1.set_ylabel("False positive rate")
        par1.set_yscale('log')
        par1.set_ylim((10**-4,10.))
        host.axis["left"].label.set_color(p1.get_color())
        par1.axis["right"].label.set_color(p2.get_color())
        plt.xlabel('Metric value')
        plt.ylabel('Probability density')
        plt.xlim((2*np.min(data),2*np.max(data)))
        plt.grid(True)
        plt.legend(['PDF model','Tail distribution'], loc = 'lower left', fontsize=15)
        plt.ticklabel_format(style='sci', axis='x', scilimits=(0,0))
        plt.show()

    return pdf_model,new_sampling,np.array(im_histo,dtype="double"), center_bins

def get_cdf_model(data):
    pdf_model,sampling,im_histo,center_bins = get_pdf_model(data)
    return np.cumsum(pdf_model),pdf_model,sampling,im_histo,center_bins


def get_image_PDF(image,IOWA,N = 2000,centroid = None, r_step = None,Dr=None):
    IWA,OWA = IOWA
    ny,nx = image.shape

    if 0:
        fig = 1
        plt.figure(fig,figsize=(16,8))
        plt.subplot(121)
        plt.imshow(image,interpolation="nearest")
        plt.colorbar()

        data = image[np.where(np.isfinite(image))]
        im_std = np.std(data)
        bins = np.arange(np.min(data),np.max(data),im_std/10.)
        im_histo = np.histogram(data, bins=bins)[0]

        N_bins = bins.size-1
        center_bins = 0.5*(bins[0:N_bins]+bins[1:N_bins+1])
        plt.subplot(122)
        plt.plot(center_bins,np.array(im_histo,dtype="double"),'bx-', markersize=5,linewidth=3)
        plt.grid(True)
        ax = plt.gca()
        ax.set_yscale('log')
        plt.show()


    image_mask = np.ones((ny,nx))
    image_mask[np.where(np.isnan(image))] = 0

    if centroid is None :
        x_cen = np.ceil((nx-1)/2) ; y_cen = np.ceil((ny-1)/2)
    else:
        x_cen, y_cen = centroid

    # Build the x and y coordinates grids
    x, y = np.meshgrid(np.arange(nx)-x_cen, np.arange(ny)-y_cen)
    # Calculate the radial distance of each pixel
    r_grid = abs(x +y*1j)
    th_grid = np.arctan2(x,y)

    # Define the radii intervals for each annulus
    if Dr is None:
        r0 = IWA
        annuli_radii = []
        if r_step is None:
            while np.sqrt(N/np.pi+r0**2) < OWA:
                annuli_radii.append((r0,np.sqrt(N/np.pi+r0**2)))
                r0 = np.sqrt(N/np.pi+r0**2)
        else:
            while np.sqrt(N/np.pi+r0**2) < OWA:
                annuli_radii.append((r0,np.sqrt(N/np.pi+r0**2)))
                r0 += r_step

        annuli_radii.append((r0,np.max([ny,nx])))
    else:
        annuli_radii = []
        for r in np.arange(IWA+Dr,OWA-Dr,Dr):
            annuli_radii.append((r-Dr,r+Dr))
    N_annuli = len(annuli_radii)


    pdf_list = []
    cdf_list = []
    sampling_list = []
    annulus_radii_list = []
    if 0:
        rings = np.zeros((ny,nx))+np.nan
    for it, rminmax in enumerate(annuli_radii):
        r_min,r_max = rminmax
        #print(rminmax)

        where_ring = np.where((r_min< r_grid) * (r_grid < r_max) * image_mask)
        #print(np.size(where_ring[0]))
        if 0:
            image_tmp = copy(image)
            image_tmp[where_ring] = np.nan
            plt.figure(2)
            plt.imshow(image_tmp,interpolation="nearest")
            plt.show()
        if 0:
            rings[where_ring] = it

        data = image[where_ring]
        cdf_model, pdf_model, sampling, im_histo, center_bins  = get_cdf_model(data)

        pdf_list.append(pdf_model)
        cdf_list.append(cdf_model)
        sampling_list.append(sampling)
        annulus_radii_list.append(((r_min+r_max)/2.,r_min,r_max))
        if 0:
            fig = 1
            plt.figure(fig,figsize=(8,8))
            plt.subplot(np.ceil(np.sqrt(N_annuli)),np.ceil(np.sqrt(N_annuli)),it)
            plt.plot(sampling,pdf_model,'b-',linewidth=3)
            plt.plot(sampling,1.-cdf_model,'r-',linewidth=3)
            plt.xlabel('criterion value', fontsize=20)
            plt.ylabel('Probability of the value', fontsize=20)
            plt.grid(True)
            ax = plt.gca()
            ax.tick_params(axis='x', labelsize=20)
            ax.tick_params(axis='y', labelsize=20)
            ax.legend(['flat cube histogram','flat cube histogram (Gaussian fit)','planets'], loc = 'upper right', fontsize=12)
            ax.set_yscale('log')
            plt.ylim((10**-7,10))

    if 0:
        plt.figure(2,figsize=(8,8))
        plt.imshow(rings,interpolation="nearest")
        plt.show()



    return pdf_list, cdf_list, sampling_list, annulus_radii_list


def get_image_stddev(image,IOWA,N = 2000,centroid = None, r_step = None,Dr=None):
    IWA,OWA = IOWA
    ny,nx = image.shape

    image_mask = np.ones((ny,nx))
    image_mask[np.where(np.isnan(image))] = 0

    if centroid is None :
        x_cen = np.ceil((nx-1)/2) ; y_cen = np.ceil((ny-1)/2)
    else:
        x_cen, y_cen = centroid

    # Build the x and y coordinates grids
    x, y = np.meshgrid(np.arange(nx)-x_cen, np.arange(ny)-y_cen)
    # Calculate the radial distance of each pixel
    r_grid = abs(x +y*1j)
    th_grid = np.arctan2(x,y)

    # Define the radii intervals for each annulus
    if Dr is None:
        r0 = IWA
        annuli_radii = []
        if r_step is None:
            while np.sqrt(N/np.pi+r0**2) < OWA:
                annuli_radii.append((r0,np.sqrt(N/np.pi+r0**2)))
                r0 = np.sqrt(N/np.pi+r0**2)
        else:
            while np.sqrt(N/np.pi+r0**2) < OWA:
                annuli_radii.append((r0,np.sqrt(N/np.pi+r0**2)))
                r0 += r_step

        annuli_radii.append((r0,np.max([ny,nx])))
    else:
        annuli_radii = []
        for r in np.arange(IWA+Dr,OWA-Dr,Dr):
            annuli_radii.append((r-Dr,r+Dr))
    #N_annuli = len(annuli_radii)


    stddev_list = []
    annulus_radii_list = []
    for it, rminmax in enumerate(annuli_radii):
        r_min,r_max = rminmax

        where_ring = np.where((r_min< r_grid) * (r_grid < r_max) * image_mask)

        data = image[where_ring]

        stddev_list.append(np.nanstd(data))
        annulus_radii_list.append(((r_min+r_max)/2.,r_min,r_max))

    return stddev_list, annulus_radii_list


def get_image_stat_map(image,image_without_planet,mask_radius = 7, use_mask_per_pixel = False, IOWA = None,N = 3000,centroid = None, r_step = 5, mute = True,N_threads =None,Dr= None, proba = True):
    if use_mask_per_pixel:
        return get_image_stat_map_perPixMasking(image,image_without_planet,mask_radius = mask_radius, IOWA = IOWA,N = N,centroid = centroid, mute = mute,N_threads = N_threads,Dr= Dr, proba = proba)
    else:
        return get_image_stat_map_noPlanet(image,image_without_planet = image_without_planet,IOWA = IOWA,N = N,centroid = centroid, r_step = r_step, mute = mute,Dr= Dr, proba = proba)

def get_image_stat_map_perPixMasking_threadTask_star(params):
    """
    Convert `f([1,2])` to `f(1,2)` call.
    It allows one to call get_image_probability_map_perPixMasking_threadTask() with a tuple of parameters.
    """
    return get_image_stat_map_perPixMasking_threadTask(*params)

def get_image_stat_map_perPixMasking_threadTask(row_indices,
                                               col_indices,
                                               image,
                                               image_without_planet,
                                               x_grid,
                                               y_grid,
                                               N,
                                               mask_radius,
                                               firstZone_radii,
                                               lastZone_radii,
                                               Dr = None,
                                               proba = True):
    ny,nx = image.shape

    #print(row_indices)

    image_without_planet_mask = np.ones((ny,nx))
    image_without_planet_mask[np.where(np.isnan(image_without_planet))] = 0

    r_limit_firstZone,r_min_firstZone,r_max_firstZone = firstZone_radii
    r_limit_lastZone,r_min_lastZone,r_max_lastZone = lastZone_radii

    # Calculate the radial distance of each pixel
    r_grid = abs(x_grid +y_grid*1j)
    th_grid = np.arctan2(x_grid,y_grid)

    N_it = row_indices.size
    proba_or_SNR_map = np.zeros((N_it)) + np.nan
    #stdout.write("\r%d" % 0)
    for id,k,l in zip(range(N_it),row_indices,col_indices):
        #stdout.write("\r{0}/{1}".format(id,N_it))
        #stdout.flush()

        x = x_grid[(k,l)]
        y = y_grid[(k,l)]
        #print(x,y)
        r = r_grid[(k,l)]

        if Dr is None:
            if r < r_limit_firstZone:
                #Calculate stat for pixels close to IWA
                r_min,r_max = r_min_firstZone,r_max_firstZone
            elif r > r_limit_lastZone:
                r_min,r_max = r_min_lastZone,r_max_lastZone
            else:
                dr = N/(4*np.pi*r)
                r_min,r_max = (r-dr, r+dr)
        else:
            r_min,r_max = (r-Dr, r+Dr)


        where_ring = np.where((r_min< r_grid) * (r_grid < r_max) * image_without_planet_mask)
        where_ring_masked = np.where((((x_grid[where_ring]-x)**2 +(y_grid[where_ring]-y)**2) > mask_radius*mask_radius))
        #print(np.shape(where_ring_masked[0]))

        data = image_without_planet[(where_ring[0][where_ring_masked],where_ring[1][where_ring_masked])]

        if 0:
            print(image[k,l])
            im_cpy = copy(image)
            im_cpy[(where_ring[0][where_ring_masked],where_ring[1][where_ring_masked])] = np.nan
            plt.figure(1)
            plt.imshow(im_cpy)
            plt.show()

        if proba:
            cdf_model, pdf_model, sampling, im_histo, center_bins  = get_cdf_model(data)

            cdf_fit = interp1d(sampling,cdf_model,kind = "linear",bounds_error = False, fill_value=1.0)
            proba_or_SNR_map[id] = 1-cdf_fit(image[k,l])
        else:
            proba_or_SNR_map[id] = image[k,l]/np.nanstd(data)
        #print(probability_map[proba_map_k,l])


    return proba_or_SNR_map

def get_image_stat_map_perPixMasking(image,
                                     image_without_planet,
                                     mask_radius = 7,
                                     IOWA = None,
                                     N = 3000,
                                     centroid = None,
                                     mute = True,
                                     N_threads = None,
                                     Dr = None,
                                     proba = True):
    """

    :param image:
    :param image_without_planet:
    :param mask_radius:
    :param IOWA:
    :param N: Defines the width of the ring by the number of pixels it has to contain
    :param centroid:
    :param mute:
    :param N_threads:
    :param Dr: If not None defines the width of the ring as Dr. N is then ignored.
    :param proba: If True triggers proba calculation with pdf fitting. Otherwise simple stddev calculation and returns SNR.
    :return:
    """
    ny,nx = image.shape

    image_noNans = np.where(np.isfinite(image))

    if IOWA is None:
        IWA,OWA,inner_mask,outer_mask = get_occ(image, centroid = centroid)
    else:
        IWA,OWA = IOWA

    if centroid is None :
        x_cen = np.ceil((nx-1)/2) ; y_cen = np.ceil((ny-1)/2)
    else:
        x_cen, y_cen = centroid

    image_without_planet_mask = np.ones((ny,nx))
    image_without_planet_mask[np.where(np.isnan(image_without_planet))] = 0

    # Build the x and y coordinates grids
    x_grid, y_grid = np.meshgrid(np.arange(nx)-x_cen, np.arange(ny)-y_cen)
    # Calculate the radial distance of each pixel
    r_grid = abs(x_grid +y_grid*1j)
    th_grid = np.arctan2(x_grid,y_grid)

    r_min_firstZone,r_max_firstZone = (IWA,np.sqrt(N/np.pi+IWA**2))
    r_limit_firstZone = (r_min_firstZone + r_max_firstZone)/2.
    r_min_lastZone,r_max_lastZone = (OWA,np.max([ny,nx]))
    r_limit_lastZone = OWA - N/(4*np.pi*OWA)

    stat_map = np.zeros(image.shape) + np.nan
    if N_threads is not None:
        pool = NoDaemonPool(processes=N_threads)
        #pool = mp.Pool(processes=N_threads)

        N_pix = image_noNans[0].size
        chunk_size = N_pix/N_threads
        N_chunks = N_pix/chunk_size

        # Shuffle the list of indices such that a thread doesn't end up with only the outer most pixel (where the number
        # of pixels in the pdf is much bigger which make it a lot slower compared to his brothers)
        image_noNans_rows = copy(image_noNans[0])
        image_noNans_cols = copy(image_noNans[1])
        rng_state = np.random.get_state()
        np.random.shuffle(image_noNans_rows)
        np.random.set_state(rng_state)
        np.random.shuffle(image_noNans_cols)

        # Get the chunks
        chunks_row_indices = []
        chunks_col_indices = []
        for k in range(N_chunks-1):
            chunks_row_indices.append(image_noNans_rows[(k*chunk_size):((k+1)*chunk_size)])
            chunks_col_indices.append(image_noNans_cols[(k*chunk_size):((k+1)*chunk_size)])
        chunks_row_indices.append(image_noNans_rows[((N_chunks-1)*chunk_size):N_pix])
        chunks_col_indices.append(image_noNans_cols[((N_chunks-1)*chunk_size):N_pix])

        outputs_list = \
            pool.map(get_image_stat_map_perPixMasking_threadTask_star,
                       itertools.izip(chunks_row_indices,
                       chunks_col_indices,
                       itertools.repeat(image),
                       itertools.repeat(image_without_planet),
                       itertools.repeat(x_grid),
                       itertools.repeat(y_grid),
                       itertools.repeat(N),
                       itertools.repeat(mask_radius),
                       itertools.repeat((r_limit_firstZone,r_min_firstZone,r_max_firstZone)),
                       itertools.repeat((r_limit_lastZone,r_min_lastZone,r_max_lastZone)),
                       itertools.repeat(Dr),
                       itertools.repeat(proba)))

        for row_indices,col_indices,out in zip(chunks_row_indices,chunks_col_indices,outputs_list):
            stat_map[(row_indices,col_indices)] = out
        pool.close()

    else:
        stat_map[image_noNans] = \
            get_image_stat_map_perPixMasking_threadTask(image_noNans[0],
                                                               image_noNans[1],
                                                               image,
                                                               image_without_planet,
                                                               x_grid,y_grid,
                                                               N,
                                                               mask_radius,
                                                               (r_limit_firstZone,r_min_firstZone,r_max_firstZone),
                                                               (r_limit_lastZone,r_min_lastZone,r_max_lastZone),
                                                               Dr = Dr,
                                                               proba = proba)
    if proba:
        return -np.log10(stat_map)
    else:
        return stat_map



def get_image_stat_map_noPlanet(image,
                                image_without_planet,
                                IOWA = None,
                                N = 3000,
                                centroid = None,
                                r_step = 5,
                                mute = True,
                                Dr = None,
                                proba = True):
    if IOWA is None:
        IWA,OWA,inner_mask,outer_mask = get_occ(image, centroid = centroid)
    else:
        IWA,OWA = IOWA

    if proba:
        pdf_list, cdf_list, sampling_list, annulus_radii_list = get_image_PDF(image_without_planet,(IWA,OWA),N,centroid,r_step=r_step,Dr=Dr)

        pdf_radii = np.array(annulus_radii_list)[:,0]

        stat_map = np.zeros(image.shape) + np.nan
        ny,nx = image.shape

        # Build the x and y coordinates grids
        x_grid, y_grid = np.meshgrid(np.arange(nx)-centroid[0], np.arange(ny)-centroid[1])

        # Calculate the radial distance of each pixel
        r_grid = abs(x_grid +y_grid*1j)

        image_finite = np.where(np.isfinite(image))

        #Build the cdf_models from interpolation
        cdf_interp_list = []
        for sampling,cdf_sampled in zip(sampling_list,cdf_list):
            cdf_interp_list.append(interp1d(sampling,cdf_sampled,kind = "linear",bounds_error = False, fill_value=1.0))

            #f = interp1d(sampling,cdf_sampled,kind = "linear",bounds_error = False, fill_value=1.0)
            #plt.plot(np.arange(-10,10,0.1),f(np.arange(-10,10,0.1)))
            #plt.show()

        for k,l in zip(image_finite[0],image_finite[1]):
            #stdout.flush()
            #stdout.write("\r%d" % k)
            r = r_grid[k,l]

            if r < OWA:
                r_closest_id, r_closest = min(enumerate(pdf_radii), key=lambda x: abs(x[1]-r))


                if (r-r_closest) < 0:
                    r_closest_id2 = r_closest_id - 1
                else:
                    r_closest_id2 = r_closest_id + 1
                r_closest2 = pdf_radii[r_closest_id2]

                if (r_closest_id2 < 0) or (r_closest_id2 > (pdf_radii.size-1)):
                    stat_map[k,l] = 1-cdf_interp_list[r_closest_id](image[k,l])
                    #plt.plot(np.arange(-10,10,0.1),cdf(np.arange(-10,10,0.1)))
                    #plt.show()
                else:
                    stat_map[k,l] = 1-(cdf_interp_list[r_closest_id](image[k,l])*abs(r-r_closest2)+cdf_interp_list[r_closest_id2](image[k,l])*abs(r-r_closest))/abs(r_closest-r_closest2)
            else:
                    stat_map[k,l] = 1-cdf_interp_list[pdf_radii.size-1](image[k,l])

        if 0:
            plt.figure(1)
            plt.subplot(1,3,1)
            plt.imshow(np.log10(stat_map),interpolation="nearest")
            plt.colorbar()
            plt.subplot(1,3,2)
            plt.imshow(image,interpolation="nearest")
            plt.subplot(1,3,3)
            plt.imshow(image_without_planet,interpolation="nearest")
            plt.show()

        return -np.log10(stat_map)
    else:
        stddev_list, annulus_radii_list = get_image_stddev(image_without_planet,(IWA,OWA),N,centroid,r_step=r_step,Dr=Dr)

        radii = np.array(annulus_radii_list)[:,0]

        stddev_func = interp1d(radii,stddev_list,kind = "linear",bounds_error = False, fill_value=np.nan)

        stat_map = np.zeros(image.shape) + np.nan
        ny,nx = image.shape

        # Build the x and y coordinates grids
        x_grid, y_grid = np.meshgrid(np.arange(nx)-centroid[0], np.arange(ny)-centroid[1])

        # Calculate the radial distance of each pixel
        r_grid = abs(x_grid +y_grid*1j)

        image_finite = np.where(np.isfinite(image))

        for k,l in zip(image_finite[0],image_finite[1]):
            #stdout.flush()
            #stdout.write("\r%d" % k)
            r = r_grid[k,l]
            stat_map[k,l] = image[k,l]/stddev_func(r)

        return stat_map




def pdf_model_gaussAsymExp(x,m,var,var2,m_exp,alpha,beta):
    #m,var,var2,m_exp,alpha,beta = param

    pdf = np.zeros(x.shape)

    where_x_is_greater_than_m = np.where(x >= m)
    where_x_is_lower_than_m = np.where(x < m)

    pdf[where_x_is_greater_than_m] = np.exp(-(x[where_x_is_greater_than_m]-m)**2/(2*var)*np.exp(-x[where_x_is_greater_than_m]**2/(2*var2)) \
                                            - (alpha*(x[where_x_is_greater_than_m]-m)+m_exp)*(1.-np.exp(-x[where_x_is_greater_than_m]**2/(2*var2))) )
    pdf[where_x_is_lower_than_m] = np.exp(-(x[where_x_is_lower_than_m]-m)**2/(2*var)*np.exp(-x[where_x_is_lower_than_m]**2/(2*var2)) \
                                          - (-beta*(x[where_x_is_lower_than_m]-m)+m_exp)*(1.-np.exp(-x[where_x_is_lower_than_m]**2/(2*var2))) )

    pdf /= np.sum(pdf)

    return pdf

def MIN_pdf_model_gaussAsymExp(x,y,m,var,var2,m_exp,alpha,beta):
    pdf_model = pdf_model_gaussAsymExp(x,m,var,var2,m_exp,alpha,beta)
    return np.sum((y-pdf_model)**2/pdf_model)

def LSQ_pdf_model_gaussAsymExp(x,y,m,var,var2,m_exp,alpha,beta):
    pdf_model = pdf_model_gaussAsymExp(x,m,var,var2,m_exp,alpha,beta)
    return (y-pdf_model)**2/pdf_model


"""
        if 1:
            print(rminmax)
            im_histo_max = np.max(im_histo)

            g_init = models.Gaussian1D(amplitude=np.max(im_histo), mean=0.0, stddev=im_std)
            fit_g = fitting.LevMarLSQFitter()
            warnings.simplefilter('ignore')
            g = fit_g(g_init, bins[0:bins.size-1], im_histo)

            #m,var,var2,m_exp,alpha,beta = param
            print(g.amplitude,g.mean,g.stddev)

            #im_histo_tmp = cpy(im_histo)
            right_side = np.where(bins[0:bins.size-1] > (g.mean+2*g.stddev))
            left_side = np.where(bins[0:bins.size-1] < (g.mean-2*g.stddev))
            #im_histo_tmp[)]

            param0_rightExp = (0,0)
            param_fit_rightExp,pcov = curve_fit(pdf_model_exp, (bins[0:bins.size-1])[right_side], im_histo[right_side], p0=param0_rightExp, sigma=None)
            param0_leftExp = (0,0)
            param_fit_leftExp,pcov = curve_fit(pdf_model_exp, (bins[0:bins.size-1])[left_side], im_histo[left_side], p0=param0_leftExp, sigma=None)
            print(param_fit_rightExp,param_fit_leftExp)

            LSQ_func = lambda para: LSQ_pdf_model_exp((bins[0:bins.size-1])[right_side], im_histo[right_side],para[0],para[1])
            param_fit_rightExp2 = leastsq(LSQ_func,param0_rightExp)
            LSQ_func = lambda para: LSQ_pdf_model_exp((bins[0:bins.size-1])[left_side], im_histo[left_side],para[0],para[1])
            param_fit_leftExp2 = leastsq(LSQ_func,param0_leftExp)


            #param0 = (g.mean+0.0,g.stddev+0.0,g.stddev+0.0,0,0,0)
            #param_fit,pcov = curve_fit(pdf_model_gaussAsymExp, bins[0:bins.size-1], im_histo, p0=param0, sigma=None)
            #print(param_fit)

            #param0 = [g.mean+0.0,g.stddev+0.0,g.stddev+0.0,0,0,0]
            #MIN_func = lambda para: MIN_pdf_model_gaussAsymExp(bins[0:bins.size-1],im_histo,para[0],para[1],para[2],para[3],para[4],para[5])
            #param_fit2 = minimize(MIN_func,param0, method='BFGS').x

            param0 = [g.mean+0.0,g.stddev+0.0,g.stddev+0.0,0,0,0]
            LSQ_func = lambda para: LSQ_pdf_model_gaussAsymExp(bins[0:bins.size-1],im_histo,para[0],para[1],para[2],para[3],para[4],para[5])
            param_fit3 = leastsq(LSQ_func,param0)
            print(param_fit3)

            #LSQ_func = lambda para: para1**

            fig = 1
            plt.figure(fig,figsize=(8,8))
            plt.plot(bins[0:bins.size-1],im_histo,'bx-', markersize=5,linewidth=3)
            plt.plot(bins[0:bins.size-1],g(bins[0:bins.size-1]),'c--',linewidth=1)
            #plt.plot(bins[0:bins.size-1],pdf_model_gaussAsymExp(bins[0:bins.size-1],*param_fit),'r-',linewidth=2)
            #plt.plot(bins[0:bins.size-1],pdf_model_gaussAsymExp(bins[0:bins.size-1],*param_fit2),'g-',linewidth=2)
            plt.plot(bins[0:bins.size-1],pdf_model_gaussAsymExp(bins[0:bins.size-1],*param_fit3[0]),'p-',linewidth=2)
            plt.plot((bins[0:bins.size-1])[right_side],im_histo[right_side],'r.', markersize=8)
            plt.plot((bins[0:bins.size-1])[left_side],im_histo[left_side],'g.', markersize=8)
            plt.plot((bins[0:bins.size-1])[right_side],pdf_model_exp((bins[0:bins.size-1])[right_side],*param_fit_rightExp),'r-',linewidth=2)
            plt.plot((bins[0:bins.size-1])[left_side],pdf_model_exp((bins[0:bins.size-1])[left_side],*param_fit_leftExp),'g-',linewidth=2)
            plt.plot((bins[0:bins.size-1])[right_side],pdf_model_exp((bins[0:bins.size-1])[right_side],*param_fit_rightExp2[0]),'r--',linewidth=2)
            plt.plot((bins[0:bins.size-1])[left_side],pdf_model_exp((bins[0:bins.size-1])[left_side],*param_fit_leftExp2[0]),'g--',linewidth=2)

            plt.xlabel('criterion value', fontsize=20)
            plt.ylabel('Probability of the value', fontsize=20)
            plt.xlim((-10.* im_std,10.*im_std))
            plt.grid(True)
            ax = plt.gca()
            #ax.text(10.*im_std, 2.0*im_histo_max/5., str(N_high_SNR_planets),
            #        verticalalignment='bottom', horizontalalignment='right',
            #        color='red', fontsize=50)
            #ax.text(3.*im_std, 2.0*im_histo_max/5., str(N_low_SNR_planets),
            #        verticalalignment='bottom', horizontalalignment='right',
            #        color='red', fontsize=50)
            ax.tick_params(axis='x', labelsize=20)
            ax.tick_params(axis='y', labelsize=20)
            ax.legend(['flat cube histogram','flat cube histogram (Gaussian fit)','planets'], loc = 'upper right', fontsize=12)
            #plt.savefig(outputDir+"histo_"+filename+".png", bbox_inches='tight')
            #plt.clf()
            #plt.close(fig)
            ax.set_yscale('log')
            plt.ylim((10**-7,1))
            plt.show()


"""