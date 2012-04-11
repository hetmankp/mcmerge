""" Some handy vector routines """

import itertools
import numpy

def zero(v):
    """ Check if a vector is all zeros """
    return (v == numpy.zeros(v.shape, v.dtype)).all()

def decompose(v):
    """ Split into prime components """
    c, r = itertools.chain, itertools.repeat
    dims = v.shape[0]
    axes = (numpy.array(list(c(r(0, d), (1,), r(0, dims-d-1)))) for d in xrange(0, dims))
    return [vd for vd in (v*dir for dir in axes) if not zero(vd)]

def inside(v, vecs):
    """ Check if the list contains a vector """
    for vec in vecs:
        if (vec == v).all():
            return True
    return False

def uniques(vecs):
    """ Return a list of only unique vectors """
    return [numpy.array(t) for t in set(tuple(v) for v in vecs)]

def vecs2tuples(vecs):
    """ Convert list of vectors into set of tuples """
    
    return set(tuple(v) for v in vecs)

def tuples2vecs(tuples):
    """ Convert set of tuples into list of vectors """
    
    return [numpy.array(t) for t in tuples]

