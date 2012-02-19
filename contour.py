import itertools, collections
import numpy
from pymclevel import mclevel

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
    }
    
    def __init__(self):
        self.shift = {}
        self.edges = {}
    
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

