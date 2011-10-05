import sys, pickle, os.path, itertools, collections, errno, getopt
import numpy
from pymclevel import mclevel
import pymclevel.materials
import vec, carve, filter
from carve import ChunkSeed

class Contour(object):
    """
    Class for finding and recording the contour of the world. The contour
    is stored as a dictionary of tuple co-ordinates and edge direction
    vectors.
    """
    
    zenc = {-1: 'S', 0: '', 1: 'N'}
    xenc = {-1: 'E', 0: '', 1: 'W'}
    
    sdec = {'S': numpy.array([0, -1]), 'N': numpy.array([0, 1]), 'E': numpy.array([-1, 0]), 'W': numpy.array([1, 0])}
    
    def __init__(self):
        self.edges = {}
        
    def __trace_edge(self, level, chunk):
        """
        Checks surrounding chunks and records a set of
        vectors for the direction of contour faces.
        """
        
        for z in xrange(-1, 2):
            for x in xrange(-1, 2):
                curr = (chunk[0] + x, chunk[1] + z)
                if curr not in level.allChunks:
                    self.edges.setdefault(chunk, set()).add((x, z))      # Edge for our existing chunk
                    self.edges.setdefault(curr,  set()).add((-x, -z))    # Counter edge for the missing chunk
    
    def __getitem__(self, coords):
        """ Interface return a numpy.array edge representation """
        
        x, z = coords
        return [numpy.array(v) for v in self.edges[(x, z)]]
    
    def __iter__(self):
        """ Iterate over edges returning (coordinate, list of numpy array edges) tuples """
        
        for c, es in self.edges.iteritems():
            yield c, [numpy.array(e) for e in es]
    
    def trace_world(self, world_dir):
        """
        Find the contour of the existing world defining the
        edges at the contour interface.
        """
        
        self.edges = {}
        level = mclevel.fromFile(world_dir)
        for chunk in level.allChunks:
            self.__trace_edge(level, chunk)
    
    def write(self, file_name):
        """ Write to file using """
    
        with open(file_name, 'w') as f:
            for coords, edge in self.edges.iteritems():
                enc = ' '.join((''.join((self.zenc[v1], self.xenc[v0])) for v0, v1 in edge))
                f.write('%6d %6d %s\n' % (coords[0], coords[1], enc))
    
    def read(self, file_name, update=False):
        """ Read from file. If update, don't clear existing data. """
        
        with open(file_name, 'r') as f:
            if not update:
                self.edges = {}
            
            for line in f:
                arr = line.strip().split(None, 2)
                dec = set(tuple(sum(self.sdec[c] for c in s)) for s in arr[2].split())
                self.edges[(int(arr[0]), int(arr[1]))] = dec

class ChunkShaper(object):
    """
    This does processing on a single chunk worth of data
    """
    
    river_width = 4
    valley_width = 8
    valey_height = 65
    river_height = 58
    sea_level = 62
    
    shift_depth = 3
    
    def __init__(self, chunk, edge, blocks):
        """ Takes a pymclevel chunk as an initialiser """
        
        self.__blocks = blocks
        self.__chunk = chunk
        self.__edge = edge
        self.__empty = chunk.world.materials.Air
        self.__local_ids = chunk.Blocks.copy()
        self.__local_data = chunk.Data.copy()
        self.__seeder = ChunkSeed(chunk.world.RandomSeed, chunk.chunkPosition)
        self.height = self.__find_heights()
    
    def __find_heights(self):
        """ Create heigh-map based on highest solid object """
        
        mx, mz, my = self.__local_ids.shape
        height = numpy.empty((mx, mz), int)
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                for y in xrange(my - 1, -1, -1):
                    if self.__local_ids[x, z, y] in self.__blocks.terrain:
                        height[x, z] = y
                        break
                else:
                    height[x, z] = -1
        
        return height
    
    def with_river(self, height):
        """ Carve out unsmoothed river bed """
        
        mx, mz = height.shape
        mask1 = carve.make_mask((mx, mz), self.__edge, self.river_width - 1, self.__seeder)
        mask2 = carve.make_mask((mx, mz), self.__edge, self.river_width,     self.__seeder)
        res = numpy.empty((mx, mz), height.dtype)
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                if mask1[x, z]:
                    res[x, z] = self.river_height
                elif mask2[x, z]:
                    res[x, z] = self.river_height + 1
                else:
                    res[x, z] = height[x, z]
        
        return res
    
    def with_valley(self, height):
        """ Carve out area which will slope down to river """
        
        mx, mz = height.shape
        mask = carve.make_mask((mx, mz), self.__edge, self.valley_width, None)
        res = numpy.empty((mx, mz), height.dtype)
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                res[x, z] = self.valey_height if mask[x, z] else height[x, z]
        
        return res, mask
    
    def erode(self, filt_name, filt_factor):
        """ Produced a smoothed version of the original height map """
        
        ffun = getattr(filter, filter.filters[filt_name])
        
        valley, erode_mask = self.with_valley(self.height)
        carved = self.with_river(valley)
        return numpy.cast[carved.dtype](numpy.round(ffun(carved, filt_factor))), erode_mask
    
    def remove(self, smoothed, erode_mask):
        """ Remove chunk blocks according to provided height map """

        def inchunk(coords):
            """ Check the coordinates are inside the chunk """
            return all(coords[n] >= 0 and coords[n] < self.__local_ids.shape[n] for n in xrange(0, self.__local_ids.ndim))

        def place(coords, block):
            """ Put the block into the specified coordinates """
            if isinstance(block, pymclevel.materials.Block):
                self.__local_ids[coords], self.__local_data[coords] = block.ID, block.blockData
            else:
                self.__local_ids[coords], self.__local_data[coords] = block
        
        def replace(coords, high, from_ids, blocks):
            """
            Replace from_ids blocks (None == any) with specified block starting
            at the given coordinates in a column of specified height.
            """
            
            try:
                blocks = iter(blocks)
            except TypeError:
                blocks = itertools.cycle([blocks])
                
            for y in xrange(coords[2], coords[2] + high, numpy.sign(high)):
                xzy = (coords[0], coords[1], y)
                if not inchunk(xzy):
                    return
                if from_ids is None or self.__local_ids[xzy] in from_ids:
                    if self.__local_ids[xzy] not in self.__blocks.immutable:    # Leave immutable blocks alone!
                        place(xzy, blocks.next())
                
        def around(coords, block_ids):
            """ Check if block is surrounded on the sides by specified blocks """
            
            for x, z in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                loc = (coords[0] + x, coords[1] + z, coords[2])
                if inchunk(loc) and self.__local_ids[loc] not in block_ids:
                    return False
            return True
        
        # Erode blocks based on the height map
        mx, mz = self.height.shape
        removed = numpy.zeros((mx, mz), bool)
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                target = min(smoothed[x, z], self.height[x, z])
                for n, y in enumerate(xrange(target + 1, self.__local_ids.shape[2])):
                    curr, curr_data = self.__local_ids[x, z, y], self.__local_data[x, z, y]
                    below = self.__local_ids[x, z, y - 1]
                    
                    # If this is a supported block, leave it alone
                    if n == 0 and curr in self.__blocks.supported and \
                       (below in self.__blocks.terrain or below in self.__blocks.tree_trunks or below in self.__blocks.tree_leaves):
                        continue
                    
                    # Eliminate hovering trees but retain the rest
                    elif n > 0 and curr in self.__blocks.tree_trunks:
                        if below not in self.__blocks.tree_trunks:
                            # Remove tree trunk
                            place((x, z, y), self.__empty)
                            
                            # Replace with sapling
                            for (a, b), sapling in self.__blocks.tree_trunks_replace.iteritems():
                                if a == curr and b & curr_data:
                                    place((x, z, target + 1), sapling)
                                    self.__local_data[x, z, target + 1] |= 8
                                    break
                    
                    elif curr in self.__blocks.tree_leaves:
                        self.__local_data[x, z, y] |= 8
                    
                    elif curr in self.__blocks.tree_trunks:
                        continue
                    
                    # Otherwise remove the block
                    elif curr != self.__empty.ID:
                        top = []
                        
                        # Remove if removable
                        if curr not in self.__blocks.immutable:
                            # Remember what blocks were previously found at the top
                            if n == 0:
                                by = self.height[x, z]
                                top = [(self.__local_ids[x, z, yi], self.__local_data[x, z, yi])
                                        for yi in xrange(by, by - self.shift_depth, -1)
                                        if yi >= 0]
                            
                            # Decide which block to replace current block with
                            if n == 0:
                                # Move down supported blocks to new height
                                by = self.height[x, z] + 1
                                if by < self.__local_ids.shape[2]:
                                    if self.__local_ids[x, z, by] in self.__blocks.supported:
                                        new = (self.__local_ids[x, z, by], self.__local_data[x, z, by])
                                    else:
                                        new = self.__empty
                            elif y - 1 <= self.sea_level and curr in self.__blocks.water:
                                pass   # Don't remove water below sea level
                            else:
                                new = self.__empty
                            
                            # Replace current block
                            place((x, z, y), new)
                        
                        # Pretty things up a little where we've stripped things away
                        if n == 0:
                            removed[x, z] = True
                            
                            if y - 1 >= 0:
                                materials = self.__chunk.world.materials
                                
                                # River bed
                                if y - 1 <= self.sea_level:
                                    replace((x, z, y - 1), -2, None, materials.Sand)    # River bed
                                
                                # Shift down higher blocks
                                elif top:
                                    replace((x, z, y - 1), -len(top), None, top)
                                
                                # Bare dirt to grass
                                below = self.__local_ids[x, z, y - 1]
                                if below == materials.Dirt.ID:
                                    place((x, z, y - 1), materials.Grass)
        
        # Some improvements can only be made after all the blocks are eroded
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                # Skip if this areas was untouched
                if not erode_mask[x, z] and not removed[x, z]:
                    continue

                # Get our bearings
                y = min(smoothed[x, z], self.height[x, z]) + 1
                below = self.__local_ids[x, z, y - 1]
                    
                # River water
                if y <= self.sea_level:
                    replace((x, z, y), self.sea_level - y + 1, None, materials.WaterStill)  # River water
        
        self.__chunk.Blocks.data = self.__local_ids.data
        self.__chunk.Data.data = self.__local_data.data
    
    def reshape(self, filt_name, filt_factor):
        """ Reshape the original chunk to the smoothed out result """
        
        smoothed, erode_mask = self.erode(filt_name, filt_factor)
        self.remove(smoothed, erode_mask)
        self.__chunk.chunkChanged() # Update internal chunk state

class Merger(object):
    # These form the basis for the height map
    terrain = (
        # Alpha blocks
        'Bedrock', 'BlockofDiamond', 'BlockofGold', 'BlockofIron', 'Brick', 'BrickSlab', 'Clay', 'CoalOre',
        'Cobblestone', 'CobblestoneSlab', 'CrackedStoneBricks', 'DiamondOre', 'Dirt', 'DoubleBrickSlab',
        'DoubleCobblestoneSlab', 'DoubleSandstoneSlab', 'DoubleStoneSlab', 'DoubleStoneBrickSlab',
        'DoubleWoodenSlab', 'Glass', 'Glowstone', 'GoldOre', 'Grass', 'Gravel', 'IronOre', 'LapisLazuliBlock',
        'LapisLazuliOre', 'LavaActive', 'LavaStill', 'MossStone', 'MossyStoneBricks', 'Mycelium', 'NetherBrick',
        'NetherBrickStairs', 'Netherrack', 'Obsidian', 'RedstoneOre', 'RedstoneOreGlowing', 'Sand', 'Sandstone',
        'SandstoneSlab', 'Snow', 'SoulSand', 'Stone', 'StoneBricks', 'StoneBrickSlab', 'StoneBrickStairs',
        'BrickStairs', 'StoneSlab', 'StoneStairs', 'HiddenSilverfishCobblestone', 'HiddenSilverfishStone',
        'HiddenSilverfishStoneBrick', 'WoodPlanks', 'WoodenSlab', 'WoodenStairs',
        
        # Classic blocks
        'Adminium', 'BlockOfDiamond', 'BlockOfGold', 'BlockOfIron', 'InfiniteLavaSource', 'Rock', 'SingleStoneSlab',
    )
    
    # These will be retained in place if there is terrain beneath to support them    
    supported = (
        'AprilFoolsChest', 'Bed', 'BirchSapling', 'Bookshelf', 'BrownMushroom', 'Cake', 'Chest',
        'CraftingTable', 'Crops', 'DesertShrub2', 'DetectorRail', 'Dispenser', 'Farmland', 'Fence', 'FenceGate',
        'Flower', 'Furnace', 'GlassPane', 'IronBars', 'IronDoor', 'JackOLantern', 'Jukebox', 'LitFurnace',
        'MelonStem', 'MonsterSpawner', 'NetherBrickFence', 'NetherWart', 'NoteBlock', 'PoweredRail', 'Pumpkin',
        'PumpkinStem', 'Rail', 'RedMushroom', 'RedstoneRepeaterOff', 'RedstoneRepeaterOn', 'RedstoneWire', 'Rose',
        'Sapling', 'Shrub', 'Sign', 'SnowLayer', 'Sponge', 'SpruceSapling', 'StoneFloorPlate', 'TNT', 'TallGrass',
        'UnusedShrub', 'Watermelon', 'Web', 'WoodFloorPlate', 'WoodenDoor',
    )
    
    # These will never be removed
    immutable = (
        'Bedrock', 'Adminium',
    )
    
    # Ignored when reshaping land
    water = (
        'Ice', 'WaterActive', 'WaterStill',
    )

    # Tree trunks
    tree_trunks = (
        'BirchWood', 'Cactus', 'Ironwood', 'HugeBrownMushroom', 'HugeRedMushroom', 'SugarCane', 'Vines', 'Wood',
    )
    
    # Leaves and their decayed versions
    tree_leaves = (
        'BirchLeaves', 'BirchLeavesDecaying', 'Leaves', 'LeavesDecaying', 'PineLeaves', 'PineLeavesDecaying',
    )
    
    # Tree trunk replace
    tree_trunks_replace = {
        'BirchWood': 'BirchSapling', 'Ironwood': 'SpruceSapling', 'Wood': 'Sapling',
    }
    
    BlockIDs = collections.namedtuple('BlockIDs', ['terrain', 'supported', 'immutable', 'water', 'tree_trunks', 'tree_leaves', 'tree_trunks_replace'])
    
    def __init__(self, world_dir, contour, filt_name, filt_factor):
        self.filt_name = filt_name
        self.filt_factor = filt_factor
        
        self.__level = mclevel.fromFile(world_dir)
        self.__contour = contour
        self.__blocks = self.BlockIDs(self.__block_material(self.terrain),
                                      self.__block_material(self.supported),
                                      self.__block_material(self.immutable),
                                      self.__block_material(self.water),
                                      self.__block_material(self.tree_trunks),
                                      self.__block_material(self.tree_leaves),
                                      self.__block_material(self.tree_trunks_replace, (('ID', 'blockData'), None)))
        
        self.log_interval = 1
        self.log_function = None
    
    def __block_material(self, names, attrs='ID'):
        """ Returns block attributes for those names that are present in the loaded level materials """
        
        def cycle(it):
            if it is None or isinstance(it, basestring):
                return itertools.repeat(it)
            else:
                return itertools.cycle(it)
        
        def getter(attrs):
            if attrs is None:
                return lambda obj: obj
            elif isinstance(attrs, basestring):
                return lambda obj: getattr(obj, attrs)
            else:
                return lambda obj: tuple(obj if attr is None else getattr(obj, attr) for attr in attrs)
        
        materials = self.__level.materials
        if hasattr(names, 'iteritems'):
            atrs = [getter(attr) for attr in itertools.islice(cycle(attrs), 2)]
            return dict([atrs[i](getattr(materials, n)) for i, n in enumerate(ns)]
                        for ns in names.iteritems()
                        if all(hasattr(materials, n) for n in ns))
        else:
            atr = getter(attrs)
            return set(atr(getattr(materials, n)) for n in names if hasattr(materials, n))
    
    def __have_surrounding(self, coords, edge):
        """ Check if all surrounding fault line chunks are present """

        if coords not in self.__level.allChunks:
            return False
        
        for x, z in edge:
            if (coords[0] + x, coords[1] + z) not in self.__level.allChunks:
                return False
        return True
    
    def erode(self, contour):
        # Go through all the chunks that require smoothing
        reshaped = []
        for n, (coord, edge) in enumerate(contour.edges.iteritems()):
            # We only re-shape when surrounding fault line land is present to prevent river spillage
            if self.__have_surrounding(coord, edge):
                cs = ChunkShaper(self.__level.getChunk(*coord), contour[coord], self.__blocks)
                cs.reshape(self.filt_name, self.filt_factor)
                reshaped.append(coord)
            
            # Progress logging
            if self.log_function is not None:
                if n % self.log_interval == 0:
                    self.log_function(n)
        
        self.__level.saveInPlace()
        return reshaped

if __name__ == '__main__':
    # Define some defaults
    contour_file_name = 'contour.dat'
    filt_factor = 1.7
    filt_name = 'smooth'
    trace_mode = False
    
    # Helpful usage information
    def usage():
        print "Usage: %s [options] <world_dir>" % os.path.basename(sys.argv[0])
        print
        print "Stitches together existing Minecraft map regions with newly generated areas"
        print "by separating them with a river."
        print
        print "Uses a two phase process. First trace out the contour of the original map"
        print "with the --trace mode. After generating the new areas, stitch them together"
        print "by running in the default mode. The stitching phase may be executed multiple"
        print "times if not all new chunks bordering with the old map are available."
        print
        print "Options:"
        print "-h, --help                    displays this help"
        print "-t, --trace                   tracing mode generates contour data for the"
        print "                              original world before adding new areas"
        print "-s, --smooth=<factor>         smoothing filter factor, default: %.2f" % filt_factor
        print "-f, --filter=<filter>         name of filter to use, default: %s" % filt_name
        print "                              available: %s" % ', '.join(filter.filters.iterkeys())
        print "-c, --contour=<file_name>     file that records the contour data in the"
        print "                              world directory, default: %s" % contour_file_name
        print
        print "-r, --river-width=<val>       width of the river, default: %d" % (ChunkShaper.river_width*2)
        print "-v, --valley-width=<val>      width of the valley, default: %d" % (ChunkShaper.valley_width*2)
        print "    --river-height=<val>      y co-ord of river bottom, default: %d" % ChunkShaper.river_height
        print "    --valley-height=<val>     y co-ord of valley bottom, default: %d" % ChunkShaper.valey_height
        print
        print "    --river-centre-deviation=<low>,<high>"
        print "                              lower and upper bound on river centre"
        print "                              deviation, default: %d,%d" % carve.river_deviation_centre
        print "    --river-width-deviation=<low>,<high>"
        print "                              lower and upper bound on river width"
        print "                              deviation, devault: %d,%d" % carve.river_deviation_width
        print "    --river-centre-bend=<dst> distance between river centre bends"
        print "                              default: %.1f" % carve.river_frequency_centre
        print "    --river-width-bend=<dst>  distance between river width bends"
        print "                              default: %.1f" % carve.river_frequency_width
        print
        print "    --sea-level=<val>         y co-ord of sea level, default: %d" % ChunkShaper.sea_level
        print "    --narrow-factor=<val>     amount to narrow river/valley when found on"
        print "                              both sides of a chunk, default: %.2f" % carve.narrowing_factor
        print "    --cover-depth=<val>       depth of blocks from surface that will be shifted"
        print "                              down to form new eroded surface, default: %d" % ChunkShaper.shift_depth
    
    def error(msg):
        print "For usage type: %s --help" % os.path.basename(sys.argv[0])
        print
        print "Error: %s" % msg
        sys.exit(1)
    
    # Parse parameters
    try:
        opts, args = getopt.gnu_getopt(
            sys.argv[1:],
            "hts:f:c:r:v:",
            ['help', 'trace', 'smooth=', 'filter=', 'contour=', 'river-width=',
             'valley-width=', 'river-height=', 'valley-height=',
             'river-centre-deviation=', 'river-width-deviation=',
             'river-centre-bend=', 'river-width-bend=',
             'sea-level=', 'narrow-factor=', 'cover-depth=']
        )

    except getopt.GetoptError, e:
        error(e)
    
    if any(opt in ('-h', '--help') for opt, _ in opts):
        usage()
        sys.exit(0)
    
    if len(args) < 1:
        error("must provide world directory location")
    elif len(args) > 1:
        error("only one world location allowed")
    else:
        world_dir = args[0]
    
    def get_int(raw, name):
        try:
            return int(arg)
        except ValueError:
            error('%s must be an integer value' % name)
    
    def get_float(raw, name):
        try:
            return float(arg)
        except ValueError:
            error('%s must be a floating point number' % name)
    
    def get_ints(raw, name, count):
        try:
            ints = tuple(int(x) for x in raw.split(','))
            if len(ints) != count:
                raise ValueError
            return ints
        except ValueError:
            error('%s must be %d comma separated integers' % (name, count))
    
    for opt, arg in opts:
        if opt in ('-t', '--trace'):
            trace_mode = True
        elif opt in ('-s', '--smooth'):
            filt_factor = get_float(arg, 'smoothing filter factor')
        elif opt in ('-f', '--filter'):
            if arg in filter.filters:
                filt_name = arg
            else:
                error('filter must be one of: %s' % ', '.join(filter.filters.iterkeys()))
        elif opt in ('-c', '--contour'):
            contour_file_name = arg
        elif opt in ('-r', '--river-width'):
            val = get_int(arg, 'river width')
            ChunkShaper.river_width = val / 2 + val % 2
        elif opt in ('-v', '--valley-width'):
            val = get_int(arg, 'valley width')
            ChunkShaper.valley_width = val / 2 + val % 2
        elif opt == '--river-height':
            ChunkShaper.river_height = get_int(arg, 'river height')
        elif opt == '--valley-height':
            ChunkShaper.valey_height = get_int(arg, 'valley height')
        elif opt == '--river-centre-deviation':
            carve.river_deviation_centre = get_ints(arg, 'river centre deviation', 2)
        elif opt == '--river-width-deviation':
            carve.river_deviation_width = get_ints(arg, 'river width deviation', 2)
        elif opt == '--river-centre-bend':
            carve.river_frequency_centre = get_float(arg, 'river centre bend distance')
        elif opt == '--river-width-bend':
            carve.river_frequency_width = get_float(arg, 'river width bend distance')
        elif opt == '--sea-level':
            ChunkShaper.sea_level = get_int(arg, 'sea level')
        elif opt == '--narrow-factor':
            carve.narrowing_factor = get_int(arg, 'narrowing factor')
        elif opt == '--cover-depth':
            ChunkShaper.shift_depth = get_int(arg, 'cover depth')
    
    # Trace contour of the old world
    if trace_mode:
        print "Finding world contour..."
        contour = Contour()
        try:
            contour.trace_world(world_dir)
        except EnvironmentError, e:
            error('could not read world contour: %e')
        
        print "Recording world contour..."
        try:
            contour.write(os.path.join(world_dir, contour_file_name))
        except EnvironmentError, e:
            error('could not write world contour data: %e')
        
        print "World contour detection complete"
    
    # Attempt to merge new chunks with old chunks
    else:
        contour_data_file = os.path.join(world_dir, contour_file_name)
        
        if filt_name == 'gauss':
            if not hasattr(filter, 'scipy'):
                print "You must install SciPy to use this filter"
                sys.exit(1)
        
        print "Getting saved world contour..."
        contour = Contour()
        try:
            contour.read(contour_data_file)
        except EnvironmentError, e:
            if e.errno == errno.ENOENT:
                print "No contour data to merge from (use --contour to generate)"
                sys.exit(1)
            else:
                print "Couldn't read contour data: %s" % e
                sys.exit(1)
        
        print "Loading world..."
        merge = Merger(world_dir, contour, filt_name, filt_factor)
        
        print "Merging chunks:"
        print
        
        total = len(contour.edges)
        width = len(str(total))
        def progress(n):
            print ("... %%%dd/%%d (%%.1f%%%%)" % width) % (n, total, 100.0*n/total)
        merge.log_interval = 10
        merge.log_function = progress
        reshaped = merge.erode(contour)
        progress(total)
        
        print
        print "Finished merging, merged: %d/%d chunks" % (len(reshaped), total)
        
        print "Updating contour data..."
        for coord in reshaped:
            del contour.edges[coord]
        
        try:
            if contour.edges:
                contour.write(contour_data_file)
            else:
                os.remove(contour_data_file)
        except EnvironmentError, e:
            error('could not updated world contour data: %e')
