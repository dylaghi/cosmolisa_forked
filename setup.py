import numpy, os, re
from setuptools import setup, find_packages
from distutils.extension import Extension
from Cython.Build import cythonize

path = os.path.realpath(__file__)
try:
    user = re.search('/Users/(.+?)/', path).group(1)
except AttributeError:
    user = ''

ext_modules=[
             Extension("cosmology",
                       sources=["cosmology.pyx"],
                       libraries=["m","lal"], # Unix-like specific
                       library_dirs = ["/Users/{0}/opt/master/lib".format(user)],
                       include_dirs=[numpy.get_include(),"/Users/{0}/opt/master/include".format(user)]
                       )
             ]

setup(
      name = "cosmology",
      ext_modules = cythonize(ext_modules),
      include_dirs=[numpy.get_include(),"/Users/{0}/opt/master/include".format(user)]
      )
ext_modules=[
             Extension("likelihood",
                       sources=["likelihood.pyx"],
                       libraries=["m","lal"], # Unix-like specific
                       library_dirs = ["/Users/{0}/opt/master/lib".format(user)],
                       include_dirs=[numpy.get_include(),"/Users/{0}/opt/master/include".format(user)]
                       )
             ]

setup(
      name = "likelihood",
      ext_modules = cythonize(ext_modules),
      include_dirs=[numpy.get_include(),"/Users/{0}/opt/master/include".format(user)]
      )

