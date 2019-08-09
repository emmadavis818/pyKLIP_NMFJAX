from setuptools import setup, find_packages
from distutils.extension import Extension
from Cython.Distutils import build_ext

setup(
    name='pyklip',
    version='1.1',
    description='pyKLIP: PSF Subtraction for Exoplanets and Disks',
    url='https://bitbucket.org/pyKLIP/pyklip',
    author='pyKLIP Developers',
    author_email='jwang@astro.berkeley.edu',
    license='BSD',
    packages=find_packages(),
    cmdclass = {'build_ext': build_ext},
    ext_modules = [Extension('matutils', ['./pyklip/empca/matutils.pyx'],
                             extra_compile_args=['-fopenmp'],
                             extra_link_args=['-fopenmp'])],
    zip_safe=False,
    classifiers=[
        # Indicate who your project is intended for
        'Intended Audience :: Science/Research',
        'Topic :: Scientific/Engineering :: Astronomy',

        # Pick your license as you wish (should match "license" above)
        'License :: OSI Approved :: BSD License',

        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.5',
        ],
    keywords='KLIP PSF Subtraction Exoplanets Astronomy',
    install_requires=['numpy', 'scipy', 'astropy']
    )
