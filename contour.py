import itertools, collections
import numpy
from pymclevel import mclevel
import ancillary, filter, carve, vec

class ContourLoadError(Exception):
    pass

MethodsFields = collections.namedtuple('MethodsFields', ('bit', 'symbol'))
EdgeData = ancillary.record('EdgeData', ('method', 'direction'))

class Contour(object):
    """
    Class for finding and recording the contour of the world. The contour
    is stored as a dictionary of tuple co-ordinates and edge direction
    vectors.
    """
    
    zenc = {-1: 'N', 0: '', 1: 'S'}
    xenc = {-1: 'W', 0: '', 1: 'E'}
    
    sdec = {'N': numpy.array([0, -1]), 'S': numpy.array([0, 1]), 'W': numpy.array([-1, 0]), 'E': numpy.array([1, 0])}
    
    methods = {
        'river': MethodsFields(1, 'R'),
        'even': MethodsFields(2, 'E'),
        'ocean': MethodsFields(4, 'O'),
        'tidy': MethodsFields(8, 'T'),
    }
    
    class SelectOperation(object):
        __metaclass__ = ancillary.Enum
        __elements__ = ('union', 'intersection', 'difference')
        
    class JoinMethod(object):
        __metaclass__ = ancillary.Enum
        __elements__ = ('add', 'replace', 'transition')
    
    def __init__(self):
        self.shift = {}         # Each coordinate maps to an integer shift distance
        self.edges = {}         # Each coordinate points to an EdgeData instance
        self.heights = {}       # Each coordinate stores a chunk height map array
    
    @property
    def empty(self):
        # Note: self.heights only contributes ancillary data do is
        # not considered
        return not (self.shift or self.edges)
    
    def height_map(self, level, block_roles):
        """
        Returns a height map object that integrates with and
        modifies the height map data.
        """
        
        return HeightMap(self.heights, self.edges, level, block_roles)
    
    @staticmethod
    def __merge_edge(a, b):
        """Merges two edges into a new value with elements of both"""
        
        return EdgeData(a.method & b.method, a.direction + b.direction)
        
    def __surrounding(self, coord):
        """Generate coordinates of all surrounding chunks"""
        
        for z in xrange(-1, 2):
            for x in xrange(-1, 2):
                if z != 0 or x != 0:
                    yield (coord[0] + x, coord[1] + z), (x, z)
        
    def __trace_edge(self, edges, chunk, all_chunks):
        """
        Checks surrounding chunks and records a set of
        vectors for the direction of contour faces.
        """
        
        for curr, (x, z) in self.__surrounding(chunk):
            if curr not in all_chunks:
                edges.setdefault(chunk, set()).add((x, z))      # Edge for our existing chunk
                edges.setdefault(curr,  set()).add((-x, -z))    # Counter edge for the missing chunk
                
    def __trace(self, level):
        """
        Simply find edges at the interface between existing
        and missing chunks.
        """
        
        edges = {}
        all_chunks = set(level.allChunks)
        for chunk in all_chunks:
            self.__trace_edge(edges, chunk, all_chunks)
            
        return edges
    
    def __select(self, op, trace):
        """
        Selects edges from the list provided by taking the set
        operation between the exsiting and new edge sets and
        retaining the result.
        """
        
        # This will be a fairly common case so let's speed it up
        if not self.edges:
            if op == self.SelectOperation.union:
                return trace
            elif op == self.SelectOperation.intersection:
                return {}
            elif op == self.SelectOperation.difference:
                return trace
            else:
                raise NameError("unknown selection type '%s'" % op)
            
        # Find which chunks to retain in the selection
        else:
            if op == self.SelectOperation.union:
                    retain = set(trace)
            elif op == self.SelectOperation.intersection:
                    retain = set(trace) & set(self.edges)
            elif op == self.SelectOperation.difference:
                retain = set(trace) - set(self.edges)
            else:
                raise NameError("unknown selection type '%s'" % op)
            
        # Return only selected edges
        return dict((coord, trace[coord]) for coord in retain)
        
    def __join(self, op, new_methods, trace):
        """
        Joins the existing edge data with the new edge data
        provided taking care to 
        """
            
        method_bits = reduce(lambda a, x: a | self.methods[x].bit, new_methods, 0)
        
        # Speed up common case
        if not self.edges:
            return dict((k, EdgeData(method_bits, v)) for k, v in trace.iteritems())
        
        # Helpers
        def direction(coord):
            try:
                return self.edges[coord].direction
            except KeyError:
                return trace[coord]
        
        # Add merge method bits to the selected trace data
        edges = {}
        for coord in trace.iterkeys():
            # Combine original merge method with new method
            if op == self.JoinMethod.add:
                try:
                    org_method = self.edges[coord].method
                except KeyError:
                    edges[coord] = EdgeData(method_bits, direction(coord))
                else:
                    edges[coord] = EdgeData(org_method & method_bits, direction(coord))
                    
            # Only record the new merge method
            elif op in (self.JoinMethod.replace, self.JoinMethod.transition):
                edges[coord] = EdgeData(method_bits, direction(coord))
                
        # If we are transitioning we also need to find the chunks joining both sets
        if op == self.JoinMethod.transition:
            # Finding the joining chunks
            join = set()
            for coord in (set(edges) & set(self.edges)):
                # Get a full set of edge features
                def features(direction):
                    features = set()
                    for component in carve.get_features(vec.tuples2vecs(direction)):
                        features.update(vec.vecs2tuples(component))
                    return features
                
                # Only want edges with no overlaping directions
                if not (features(self.edges[coord].direction) & features(trace[coord])):
                    join.add(coord)
                    
            # We want the merge methods to overlap here
            for coord in join:
                original = self.edges[coord]
                edges[coord] = EdgeData(original.method | method_bits, original.direction)
            
            # Finally need to smooth all the joining areas
            method_bit = Contour.methods['tidy'].bit
            for coord in join:
                edges[coord].method |= method_bit
                for around, _ in self.__surrounding(coord):
                    try:
                        edges[around].method |= method_bit
                    except KeyError:
                        pass
                
        return edges
            
    def trace_world(self, world_dir, methods):
        """
        Find the contour of the existing world defining the
        edges at the contour interface.
        """
        
        method_bits = reduce(lambda a, x: a | self.methods[x].bit, methods, 0)
        trace = self.__trace(mclevel.fromFile(world_dir))
        self.edges = dict((k, EdgeData(method_bits, v)) for k, v in trace.iteritems())
            
    def trace_combine(self, world_dir, combine, methods, select, join):
        """
        Find the contour at the interface between existing and empty
        chunks, then merge appropriately with existing data.
        """
        
        level = mclevel.fromFile(world_dir)
        trace = self.__trace(mclevel.fromFile(world_dir))
        trace = self.__select(select, trace)
        edges = self.__join(join, methods, trace)
        if combine:
            self.edges.update(edges)
        else:
            self.edges = edges
    
    def write(self, file_name):
        """ Write to file using """
    
        with open(file_name, 'w') as f:
            # Write header
            f.write('VERSION 2\n')
            
            # Collect all data
            blocks = set(self.edges.keys()) | set(self.shift.keys())
            for coords in blocks:
                # Assemble the block shifting data
                try:
                    shift = self.shift[coords]
                    shift_data = '% 5d' % shift
                except LookupError:
                    shift_data = '%5s' % '-'
                    
                # Assemble the edge merging data
                try:
                    edge = self.edges[coords]
                    method_data = ''.join(m.symbol for m in self.methods.itervalues() if m.bit & edge.method)
                    direction = ' '.join((''.join((self.zenc[v1], self.xenc[v0])) for v0, v1 in edge.direction))
                    edge_data = ('%%-%ds %%s' % len(self.methods)) % (method_data, direction)
                except LookupError:
                    edge_data = '-'
                
                # Write complete set of data to output
                f.write('%6d %6d %s %s\n' % (coords[0], coords[1], shift_data, edge_data))
    
    def read(self, file_name, update=False):
        """ Read from file. If update, don't clear existing data. """
        
        with open(file_name, 'r') as f:
            if not update:
                self.shift = {}
                self.edges = {}
                
            try:
                line = f.next()
            except StopIteration:
                return
            
            if line.startswith('VERSION'):
                version = int(line[8:])
                lines = f
            else:
                version = 1
                lines = itertools.chain([line], f)
                
            try:
                getattr(self, '_Contour__read_v%d' % version)(lines)
            except AttributeError:
                raise ContourLoadError("unknown version format '%s'")
                
    def __read_v1(self, lines):
        for line in lines:
            arr = line.strip().split(None, 2)
            direction = set(tuple(sum(-self.sdec[c] for c in s)) for s in arr[2].split())
            self.edges[(int(arr[0]), int(arr[1]))] = EdgeData(self.methods['river'].bit, direction)
            
    def __read_v2(self, lines):
        for line in lines:
            arr = line.strip().split(None, 4)
            coords = (int(arr[0]), int(arr[1]))
            
            if arr[2] != '-':
                self.shift[coords] = int(arr[2])
                
            if arr[3] != '-':
                method = sum(sum(m.bit for m in self.methods.itervalues() if m.symbol == s) for s in arr[3])
                direction = set(tuple(sum(self.sdec[c] for c in s)) for s in arr[4].split())
                self.edges[coords] = EdgeData(method, direction)

class HeightMap(object):
    """
    This object is used to provide height map arrays at requested
    coordinates. Requested height maps are cached and the ones that
    are no longer required for merging may be explicitly pruned.
    """
    
    def __init__(self, heights, edges, level, block_roles):
        self.__heights = heights
        self.__edges = edges
        self.__level = level
        self.__block_roles = block_roles
        self.__deferred = set()
        
    def __getitem__(self, key):
        try:
            return self.__heights[key]
        except KeyError:
            chunk = self.__level.getChunk(*key)
            height = self.find_heights(chunk.Blocks, self.__block_roles)
            self.__heights[key] = height
            return height
    
    @property
    def invalidations(self):
        """
        This set specifies items for deferred invalidation. It
        behaves exactly like a Python set() object.
        """
        
        return self.__deferred
    
    def invalidate(self, key):
        """
        Invalidate the value found under the specified key so that
        it is re-calculated next time it is requested.
        """
        
        try:
            del self.__heights[key]
        except KeyError:
            pass
    
    def invalidate_deferred(self):
        """
        Invalidates all items specifed by the self.invalidations
        set.
        """
        
        for key in self.__deferred:
            try:
                del self.__heights[key]
            except KeyError:
                pass
        self.__deferred.clear()
    
    def invalidate_all(self):
        """
        Invalidate all items immediately.
        """
        
        self.__heights.clear()
    
    def prune(self):
        """
        Removes height maps no longer needing caching given the
        remaining set of contour edges. This prunes the heights
        dictionary used to initialise this object.
        """
        
        # This is not terribly efficient but we'll let the
        # profiler decide later
        
        range = (-filter.padding, filter.padding+1)
        
        def still_required(coords):
            for z in xrange(*range):
                for x in xrange(*range):
                    if (coords[0] + x, coords[1] + z) in self.__edges:
                        return False
            return True
        
        for coord in self.__heights.keys():
            if not still_required(coord):
                del self.__heights[coord]
        
    @staticmethod
    def find_heights(block_ids, block_roles):
        """ Create heigh-map based on highest solid object """
        
        mx, mz, my = block_ids.shape
        height = numpy.empty((mx, mz), int)
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                for y in xrange(my - 1, -1, -1):
                    if block_ids[x, z, y] in block_roles.terrain:
                        height[x, z] = y
                        break
                else:
                    height[x, z] = -1
        
        return height
