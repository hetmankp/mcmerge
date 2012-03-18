import itertools, collections
import numpy
from pymclevel import mclevel
import filter

class ContourLoadError(Exception):
    pass

MethodsFields = collections.namedtuple('MethodsFields', ('bit', 'symbol'))
EdgeData = collections.namedtuple('EdgeData', ('method', 'direction'))

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
        'average': MethodsFields(2, 'A'),
        'ocean': MethodsFields(4, 'O'),
    }
    
    def __init__(self):
        self.shift = {}         # Each coordinate maps to an integer shift distance
        self.edges = {}         # Each coordinate points to an EdgeData instance
        self.heights = {}       # Each coordinate stores a chunk height map array
    
    def __surrounding(self, coord):
        """Generate coordinates of all surrounding chunks"""
        
        for z in xrange(-1, 2):
            for x in xrange(-1, 2):
                if z != 0 or x != 0:
                    yield (coord[0] + x, coord[1] + z), (x, z)
        
    def __trace_edge(self, chunk, method, all_chunks):
        """
        Checks surrounding chunks and records a set of
        vectors for the direction of contour faces.
        """
        
        for curr, (x, z) in self.__surrounding(chunk):
            if curr not in all_chunks:
                new = lambda: EdgeData(method, set())
                self.edges.setdefault(chunk, new()).direction.add((x, z))     # Edge for our existing chunk
                self.edges.setdefault(curr,  new()).direction.add((-x, -z))   # Counter edge for the missing chunk
                
    def height_map(self, level, block_roles):
        """
        Returns a height map object that integrates with and
        modifies the height map data.
        """
        
        return HeightMap(self.heights, self.edges, level, block_roles)
    
    def trace_world(self, world_dir):
        """
        Find the contour of the existing world defining the
        edges at the contour interface.
        """
        
        self.edges = {}
        level = mclevel.fromFile(world_dir)
        all_chunks = set(level.allChunks)
        for chunk in all_chunks:
            self.__trace_edge(chunk, self.methods['river'].bit, all_chunks)
    
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
                    shift_data = '%d' % shift
                except LookupError:
                    shift_data = '-'
                    
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
        
    def __getitem__(self, key):
        try:
            return self.__heights[key]
        except KeyError:
            chunk = self.__level.getChunk(*key)
            height = self.find_heights(chunk.Blocks, self.__block_roles)
            self.__heights[key] = height
            return height
        
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
