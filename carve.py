""" Masks areas to be carved out based on contour """

import itertools
import numpy
import vec

narrowing_factor = 1.5  # Used when river occupies both sides of a chunk
corner_radius_offset = 0.9

def trace_ellipse(centre, axes, bound=((0, 0), (15, 15))):
    # Ellipse interior checking function
    abs_axes = numpy.abs(numpy.array(axes)) - corner_radius_offset
    ax2, az2 = numpy.power(abs_axes, 2)
    in_ellipse = lambda x, z: (float(x)**2/ax2 + float(z)**2/az2 < 1)
    
    # Step through possible points until we find one in ellipse
    upper = int(numpy.floor(abs_axes[1]))
    for x in xrange(0, int(numpy.floor(abs_axes[0])) + 1):
        for z in xrange(upper, -1, -1):
            if in_ellipse(x, z):
                upper = z
                point = numpy.cast[int](centre + numpy.sign(axes)*numpy.array([x, z]))
                if (numpy.array(bound[0]) <= point).all() and (numpy.array(bound[1]) >= point).all():
                    yield point
                break

def mask_square(shape, inner, outer):
    """
    Create an appropriately sized boolean mask with the
    defined corner coordinates.
    """
    
    a = numpy.zeros(shape, dtype=bool)
    mx, my = shape
    for x in xrange(inner[0], outer[0]):
        a.data[mx*x+inner[1]:mx*x+outer[1]] = '\x01'*(outer[1] - inner[1])
        
    return a

def mask_lines(shape, limits, start=0, step=1):
    """
    Accepts a list of tuples with (start, end) horizontal
    ranges. Start from specified x coordinate.
    """
    
    a = numpy.zeros(shape, dtype=bool)
    mx, my = shape
    
    x = start
    for line in limits:
        if x < 0 or x >= mx:
            break
        start = my if line[0] > my else line[0]
        end   = my if line[1] > my else line[1]
        a.data[mx*x+start:mx*x+end] = '\x01'*(end - start)
        x += step
        
    return a

def mask_edge(shape, width, v):
    """ Create mask for one side of an area """
    
    if any(v < 0):
        return mask_square(shape, numpy.zeros(2, int), numpy.array(shape) + v*(numpy.array(shape) - width))
    else:
        return mask_square(shape, v*(numpy.array(shape) - width), numpy.array(shape))

def mask_corner(shape, widths, v):
    """ Creates mask for one corner of an area """
    
    vx, vz = vec.decompose(v)
    return numpy.logical_and(mask_edge(shape, widths[0], vx), mask_edge(shape, widths[1], vz))

def mask_concave_corner(shape, widths, v):
    """ Creates mask for one corner of an area """
    
    centre = (v+1)/2 * (numpy.array(shape) - 1)
    sign = numpy.sign(v)
    ellipse = trace_ellipse(centre, -sign*widths, (numpy.zeros(len(shape), int), numpy.array(shape) - 1))
    limits = (numpy.sort([centre[1], z]) + numpy.array([0, 1]) for x, z in ellipse)
    return mask_lines(shape, limits, centre[0], -sign[0])

def mask_convex_corner(shape, widths, v):
    """ Creates mask for one corner of an area """
    
    corner = (v+1)/2 * (numpy.array(shape) - 1)
    sign = numpy.sign(v)
    centre = corner - 2*sign*widths + sign*numpy.ones(corner.ndim, corner.dtype)
    ellipse = list(trace_ellipse(centre, sign*widths, (numpy.zeros(len(shape), int), numpy.array(shape) - 1)))
    clipped = numpy.maximum(numpy.minimum(centre, numpy.array(shape) - 1), numpy.zeros(len(shape), int))
    limits1 = [numpy.sort([corner[1], z + sign[1]]) + numpy.array([0, 1]) for x, z in ellipse]
    limits2 = (numpy.sort([corner[1], clipped[1]]) + numpy.array([0, 1]) for z in xrange(0, shape[0] - len(limits1)))
    return mask_lines(shape, itertools.chain(limits1, limits2), clipped[0], sign[0])

def get_straights(edge):
    """ Get vectors representing straight edges """
    
    return [v for v in edge if v[0] == 0 or v[1] == 0]

def get_induced_corners(edge):
    """ These corners are induced by straight edges """
    
    corners = []
    for x in (-1, 1):
        for z in (-1, 1):
            corner = numpy.array([x, z])
            if all(vec.inside(v, edge) for v in vec.decompose(corner)):
                corners.append(corner)
    return corners

def get_corners(edge, straights):
    """ Get vectors representing corners """
    
    concave_corners = []
    convex_corners = []
    for corner in (v for v in edge if v[0] != 0 and v[1] != 0):
        # Are the corner component vectors in straight edges?
        in_straight = [vec.inside(v, straights) for v in vec.decompose(corner)]
        
        # If all or none of the component vectors are in straight edges then it's a real corner
        if all(in_straight):
            convex_corners.append(corner)
        elif not any(in_straight):
            concave_corners.append(corner)
        
    return concave_corners, convex_corners

def make_mask_straights(shape, width, components, straights):
    """ Make a mask out of all straight edge types """
    
    mask = numpy.zeros(shape, dtype=bool)
    for v in straights:
        rwidth = int(numpy.round(width/narrowing_factor)) if vec.inside(-v, components) else int(numpy.round(width))
        mask = numpy.logical_or(mask, mask_edge(shape, rwidth, v))
        
    return mask

def make_mask_corners(shape, width, components, concave, convex):
    """ Make a mask out of all corners """
    
    mask = numpy.zeros(shape, dtype=bool)
    for corners, masker in ((concave, mask_concave_corner), (convex, mask_convex_corner)):
        for v in corners:
            xwidth = int(numpy.round(width/narrowing_factor)) if vec.inside(v*numpy.array([-1,  0], int), components) else int(numpy.round(width))
            zwidth = int(numpy.round(width/narrowing_factor)) if vec.inside(v*numpy.array([ 0, -1], int), components) else int(numpy.round(width))
            mask = numpy.logical_or(mask, masker(shape, (xwidth, zwidth), v))
    
    return mask

def make_mask(shape, edge, width):
    """ Make a mask representing a valley out of a countour edge specification """
    
    straights = get_straights(edge)
    all_corners = itertools.chain(edge, (x for x in get_induced_corners(edge) if not vec.inside(x, edge)))
    concave, convex = get_corners(all_corners, straights)
    components = vec.uniques(itertools.chain.from_iterable(vec.decompose(v) for v in itertools.chain(straights, concave, convex)))
    return numpy.logical_or(
        make_mask_straights(shape, width, components, straights),
        make_mask_corners(shape, width, components, concave, convex)
    )
