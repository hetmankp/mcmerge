""" Masks areas to be carved out based on contour """

import itertools
import numpy, scipy.interpolate, numpy.random
import vec

narrowing_factor = 1.5  # Used when river occupies both sides of a chunk
corner_radius_offset = 0.9

river_deviation_centre = (-2, 2)
river_deviation_width = (-1, 1)
river_frequency_centre = 5.1
river_frequency_width = 2.8


class ChunkSeed(object):
    """
    Used to seed generation of chunk specific features such
    as winding rivers.
    """
    
    def __init__(self, level_seed, location):
        self.level_seed = numpy.cast[int](numpy.array(level_seed))
        self.location = numpy.cast[int](numpy.array(location))
    
    def offset(self, relative):
        """
        Returns another ChunkSeed object for a chunk offset
        by the specified amount.
        """
        
        return ChunkSeed(self.level_seed, self.location + numpy.array(relative))
    
    def __side_seed(self, side):
        # Generated seeds will be the same for shared edges
        side = self.location + numpy.cast[int]((side + numpy.ones(len(side)))/2)
        return side*self.level_seed
    
    def centre_seed(self, side):
        """ Seed for river centre generation """
        
        return numpy.cast[numpy.int32](self.__side_seed(side))

    def width_seed(self, side):
        """ Seed for river width generation """
        
        return numpy.cast[numpy.int32](self.__side_seed(side)*2)

class Meander(object):
    """
    Using the 'seed' integer, used to produce a series of
    values sampled at an integral interval, interpolated from
    a random series at interval 'step' found in the
    specified 'range'.
    
    If a final value is specified for the output series
    then it's allowed to deviate by the 'final_precision'
    fraction of the full range.
    """
    
    def __init__(self, seed, step, range=(-1, 1), final_precision=0.05):
        self.seed = seed
        self.step = step
        self.range = range
        self.final_precision = final_precision
    
    def first(self):
        """
        Return value of the first point of the generated
        series.
        """
        
        gen = numpy.random.mtrand.RandomState(self.seed)
        return int(numpy.round(gen.uniform(self.range[0], self.range[1], 1)[0]))
        
    def series(self, points, final=None):
        """
        Produces a 'points' number long series of interpolated
        values. If a 'final' vale is supplied then the last
        value in the returned series will match this value to
        within the precision specified by 'final_precision'.
        """
        
        # Get the source random samples
        source_points = int(numpy.ceil(float(points)/self.step))
        
        gen = numpy.random.mtrand.RandomState(self.seed)
        y1 = gen.uniform(self.range[0], self.range[1], source_points)
        #x1 = numpy.linspace(-(float(source_points) % step), float(points) - 1, source_points)
        x1 = numpy.linspace(0, float(points) + float(source_points) % self.step - 1, source_points)
        
        # Adjust final sample to meet required result
        if final is not None:
            accept = abs(self.range[1] - self.range[0])*self.final_precision
            for i in xrange(0, 20): # Really shouldn't go deeper than this but let's be sure
                f = scipy.interpolate.interp1d(x1, y1, kind='cubic')
                error = final - f(float(points) - 1)
                if abs(error) < accept:
                    break
                else:
                   y1[-1] = y1[-1] + error 
        
        # Find interpolated points
        x2 = numpy.linspace(0.0, float(points) - 1, points)
        y2 = scipy.interpolate.interp1d(x1, y1, kind='cubic')(x2)
        
        return numpy.cast[int](numpy.round(y2))

def river_shore(shape, seed, base_width, v):
    """
    Produce a series of points representing a meandering river width
    """
    
    # Set up some required variables
    axis, axis_inv = (0, 1) if v[0] != 0 else (1, 0)
    next = numpy.ones(len(v), v.dtype); next[axis] = 0
    centre_range = numpy.array(river_deviation_centre)
    width_range =  numpy.array(river_deviation_width)
    
    # Discover the final point in the sequence based on the next block over
    final_centre = Meander(seed.offset(next).centre_seed(v), river_frequency_centre, centre_range).first()
    final_width = Meander(seed.offset(next).width_seed(v), river_frequency_width, width_range).first()
    
    # Find the centre and width sequences that will contribute to the overall river
    river_centres = Meander(seed.centre_seed(v), river_frequency_centre, centre_range).series(shape[axis_inv], final_centre)
    river_widths = Meander(seed.width_seed(v), river_frequency_width, width_range).series(shape[axis_inv], final_width)
    
    # Add everything up and make sure river never moves out of the chunk
    widths = (base_width + c*v[axis] + w for c, w in itertools.izip(river_centres, river_widths))
    return [w if w > 1 else 1 for w in widths]

def trace_ellipse(centre, axes, bound=((0, 0), (15, 15))):
    """
    Trace the pixels of a quadrant of a specified ellipse
    constrained to within a given window.
    """
    
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

def mask_edge(shape, v, widths):
    """ Create mask for one side of an area out of a sequence of widths """
    
    axis = 0 if v[0] != 0 else 1
    limits = ((0, x) for x in widths) if any(v < 0) else ((shape[axis] - x, shape[axis]) for x in widths)
    vert = mask_lines(shape, limits)
    return vert.T if axis == 0 else vert

def mask_concave_corner(shape, v, widths):
    """ Creates mask for one corner of an area """
    
    centre = (v+1)/2 * (numpy.array(shape) - 1)
    sign = numpy.sign(v)
    ellipse = trace_ellipse(centre, -sign*widths, (numpy.zeros(len(shape), int), numpy.array(shape) - 1))
    limits = (numpy.sort([centre[1], z]) + numpy.array([0, 1]) for x, z in ellipse)
    return mask_lines(shape, limits, centre[0], -sign[0])

def mask_convex_corner(shape, v, widths):
    """ Creates mask for one corner of an area """
    
    corner = (v+1)/2 * (numpy.array(shape) - 1)
    sign = numpy.sign(v)
    centre = corner + sign - 2*sign*widths
    ellipse = list(trace_ellipse(centre, sign*widths, (numpy.zeros(len(shape), int), numpy.array(shape) - 1)))
    clipped = numpy.maximum(numpy.minimum(centre, numpy.array(shape) - 1), numpy.zeros(len(shape), int))
    limits1 = [numpy.sort([corner[1], z + sign[1]]) + numpy.array([0, 1]) for x, z in ellipse]
    limits2 = (numpy.sort([corner[1], clipped[1]]) + numpy.array([0, 1]) for z in xrange(0, shape[0] - len(limits1)))
    return mask_lines(shape, itertools.chain(limits1, limits2), clipped[0], sign[0])

def make_mask_straights(shape, width, seed, components, straights):
    """ Make a mask out of all straight edge types """
    
    mask = numpy.zeros(shape, dtype=bool)
    for v in straights:
        base_width = int(numpy.round(width/narrowing_factor)) if vec.inside(-v, components) else int(numpy.round(width))
        shore = itertools.repeat(base_width) if seed is None else river_shore(shape, seed, base_width, v)
        mask = numpy.logical_or(mask, mask_edge(shape, v, shore))
        
    return mask

def make_mask_corners(shape, width, seed, components, concave, convex):
    """ Make a mask out of all corners """
    
    mask = numpy.zeros(shape, dtype=bool)
    for corners, masker in ((concave, mask_concave_corner), (convex, mask_convex_corner)):
        for v in corners:
            xwidth = int(numpy.round(width/narrowing_factor)) if vec.inside(v*numpy.array([-1,  0], int), components) else int(numpy.round(width))
            zwidth = int(numpy.round(width/narrowing_factor)) if vec.inside(v*numpy.array([ 0, -1], int), components) else int(numpy.round(width))
            
            if seed is not None and masker is mask_concave_corner:
                xwidth = river_shore(shape, seed, xwidth, v*numpy.array([1, 0]))[shape[1] - 1 if v[0] > 0 else 0]
                zwidth = river_shore(shape, seed, zwidth, v*numpy.array([0, 1]))[shape[0] - 1 if v[1] > 0 else 0]
            
            mask = numpy.logical_or(mask, masker(shape, v, (xwidth, zwidth)))
    
    return mask

def make_mask(shape, edge, width, seed):
    """ Make a mask representing a valley out of a countour edge specification """
    
    straights = get_straights(edge)
    all_corners = itertools.chain(edge, (x for x in get_induced_corners(edge) if not vec.inside(x, edge)))
    concave, convex = get_corners(all_corners, straights)
    components = vec.uniques(itertools.chain.from_iterable(vec.decompose(v) for v in itertools.chain(straights, concave, convex)))
    return numpy.logical_or(
        make_mask_straights(shape, width, seed, components, straights),
        make_mask_corners(shape, width, seed, components, concave, convex)
    )
