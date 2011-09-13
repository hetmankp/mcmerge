""" Functions necessary for smoothing 2D terrain """

import sys, pickle, os.path, itertools, collections, errno
import numpy

try:
    import scipy.ndimage
except ImportError, e:
    pass

filters = {
    'smooth':   'smooth',
    'gauss':    'gsmooth',
}

def ftrim(a, cut):
    """
    Takes a 2D DFT spectral result and removes frequencies
    above the cut off frequency.
    """
    
    b = a.copy()
    
    mx, my = b.shape
    for x in xrange(0, mx):
        for y in xrange(0, my):
            f = numpy.sqrt(min(pow(x, 2) + pow(y, 2),
                               pow(x - mx, 2) + pow(y, 2),
                               pow(x, 2) + pow(y - my, 2),
                               pow(x - mx, 2) + pow(y - my, 2)))
            b[x, y] = 0 if f > cut else a[x, y]
    
    return b

def fftrim(a, drop):
    """
    Takes a 2D DFT spectral result and removes frequencies
    according to the normalised drop off function.
    """

    b = a.copy()
    
    mx, my = b.shape
    for x in xrange(0, mx):
        for y in xrange(0, my):
            f = numpy.sqrt(min(pow(x, 2) + pow(y, 2),
                               pow(x - mx, 2) + pow(y, 2),
                               pow(x, 2) + pow(y - my, 2),
                               pow(x - mx, 2) + pow(y - my, 2)))
            b[x, y] = a[x, y]*drop(f)
    
    return b

def pad(a, extra=1):
    """
    Pad a 2D array with an extra number of equally sized
    arrays on every side. Extends the values at the edges
    of the original array in all directions.
    """
    
    def samp(c, cm):
        """ Take a sample from the edge of the input """
        
        n = c - cm*extra
        if n < 0:
            return 0
        elif n >= cm:
            return cm - 1
        else:
            return n
        
    mx, my = a.shape
    factor = extra*2+1
    
    b = numpy.empty((mx*factor, my*factor), a.dtype)
    
    for x in xrange(0, mx*factor):
        for y in xrange(0, my*factor):
            b[x, y] = a[samp(x, mx)][samp(y, my)]
            
    return b

def crop(a, extra=1):
    """
    Crop a 2D array removing an extra number of equally
    sized arrays from each edge only leaving the centre.
    """
    
    my, mx = a.shape
    mx = mx / (extra*2+1)
    my = my / (extra*2+1)
    
    b = numpy.empty((mx, my), a.dtype)
    
    for n, x in enumerate(xrange(mx*extra, mx*(extra+1))):
        b[n] = a[x][my*extra:my*(extra+1)]
        
    return b

def smooth(a, cut):
    """ Smooth by cutting out high frequencies """
    
    padding = 1         # Padding on either side
    cut *= padding*3    # Due to padding
    return crop(numpy.real(numpy.fft.ifft2(ftrim(numpy.fft.fft2(pad(a, padding)), cut))), padding)

def fsmooth(a, drop):
    """ Smooth by cutting out high frequencies, drop function defines gradual drop-off """
    
    padding = 1         # Padding on either side
    cut *= padding*3    # Due to padding
    return crop(numpy.real(numpy.fft.ifft2(fftrim(numpy.fft.fft2(pad(a, padding)), drop))), padding)

def gsmooth(a, sigma):
    """ Smooth with gaussian filter """
    
    return scipy.ndimage.filters.gaussian_filter(a, sigma, mode='nearest')
