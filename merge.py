import itertools, collections
import numpy
from pymclevel import mclevel
import pymclevel.materials
import ancillary, carve, filter, vec
from contour import Contour, HeightMap
from carve import ChunkSeed

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
    
    filt_factor_river = 1.7
    filt_factor_even = 1.0
    
    def __init__(self, chunk, contour, height_map, block_roles):
        """ Takes a pymclevel chunk as an initialiser """
        
        self.__block_roles = block_roles
        self.__chunk = chunk
        self.__contour = contour
        self.__height_map = height_map
        self.__edge = contour.edges[self.__chunk.chunkPosition]
        self.__edge_direction = vec.tuples2vecs(self.__edge.direction)
        self.__ocean = False
        self.__local_ids = chunk.Blocks.copy()
        self.__local_data = chunk.Data.copy()
        self.__seeder = ChunkSeed(chunk.world.RandomSeed, chunk.chunkPosition)
        
        self.__height_invalid = True
        self.height     # Initialise the height value
        
    @property
    def height(self):
        if self.__height_invalid:
            self.__height = HeightMap.find_heights(self.__local_ids, self.__block_roles)
            self.__height_invalid = False
            
        return self.__height
    
    def __empty_block(self, height=0):
        """ Returns block corresponding to emptiness """
        
        if self.__ocean and height <= self.sea_level:
            return self.__chunk.world.materials.Water
        else:
            return self.__chunk.world.materials.Air
    
    def with_river(self, height):
        """ Carve out unsmoothed river bed """
        
        mx, mz = height.shape
        mask1 = carve.make_mask((mx, mz), self.__edge_direction, self.river_width - 1, self.__seeder)
        mask2 = carve.make_mask((mx, mz), self.__edge_direction, self.river_width,     self.__seeder)
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
        mask = carve.make_mask((mx, mz), self.__edge_direction, self.valley_width, None)
        res = numpy.empty((mx, mz), height.dtype)
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                res[x, z] = self.valey_height if mask[x, z] else height[x, z]
        
        return res, mask
    
    def reshape(self, method, filt_name):
        """ Reshape the original chunk to the smoothed out result """
        
        if self.__edge.method & Contour.methods[method].bit:
            self.__ocean = bool(self.__edge.method & Contour.methods['ocean'].bit)
            self.__shape(method, filt_name)
            self.__chunk.chunkChanged()
        
    def __shape(self, method, filt_name):
        """ Does the reshaping work for a specific shaping method """
        
        if method == 'river':
            smoothed, erode_mask = self.erode_valley(filt_name, self.filt_factor_river)
            self.remove(smoothed, erode_mask)
        elif method in ('even', 'tidy'):
            smoothed = self.erode_slope(filt_name, self.filt_factor_even)
            self.elevate(smoothed)
            self.remove(smoothed, None)
        else:
            raise KeyError("invalid shaping method: '%s'" % method)
        
    def erode_slope(self, filt_name, filt_factor):
        """
        Produced a smoothed version of the original height map sloped
        to meet the surrounding terrain.
        """
        
        ffun = getattr(filter, filter.filters[filt_name])
        
        return numpy.cast[self.height.dtype](numpy.round(ffun(self.height, filt_factor, self.chunk_padder)))
    
    def erode_valley(self, filt_name, filt_factor):
        """
        Produced a smoothed version of the original height map with a
        river valley added around the marked edge.
        """
        
        ffun = getattr(filter, filter.filters[filt_name])
        
        valley, erode_mask = self.with_valley(self.height)
        carved = self.with_river(valley)
        return numpy.cast[carved.dtype](numpy.round(ffun(carved, filt_factor, filter.pad))), erode_mask
    
    def chunk_padder(self, a):
        """
        Pads the chunk heigh map array 'a' with surrounding chunks
        from the source world.
        """
            
        single_size = a.shape
        padded_size = tuple(x*(filter.padding*2+1) for x in single_size)
        b = numpy.empty(padded_size, a.dtype)
        
        range = (-filter.padding, filter.padding+1)
        coords = self.__chunk.chunkPosition
        
        # First fill in the surrounding land
        for z in xrange(*range):
            for x in xrange(*range):
                if z == 0 and x == 0:
                    continue
                
                xoffset = (x + filter.padding)*single_size[0]
                zoffset = (z + filter.padding)*single_size[1]
                cheight = self.__height_map[(coords[0] + x, coords[1] + z)]
                b[xoffset:xoffset+single_size[0], zoffset:zoffset+single_size[1]] = cheight
                
        # Finally add the data being padded
        xoffset = (0 + filter.padding)*single_size[0]
        zoffset = (0 + filter.padding)*single_size[1]
        b[xoffset:xoffset+single_size[0], zoffset:zoffset+single_size[1]] = a
        
        return b
    
    def elevate(self, smoothed):
        """ Add chunk blocks until they reach provided height map """

        # Erode blocks based on the height map
        mx, mz, my = self.__local_ids.shape
        materials = self.__chunk.world.materials
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                local_columns = self.__local_ids[x, z], self.__local_data[x, z]
                
                # Get target height, make sure it's in the chunk
                target = max(smoothed[x, z], self.height[x, z])
                if target > my - 1:
                    target = my - 1
                    
                # Collect details about blocks on the surface
                initial = self.height[x, z]
                below = self.__get_block(local_columns, initial)
                if self.__inchunk((x, z, initial + 1)):
                    above = self.__get_block(local_columns, initial + 1)
                else:
                    above = None
                    
                # Only supported blocks will be kept on the new surface
                if not above[0] in self.__block_roles.supported \
                or not (below[0] in self.__block_roles.terrain or
                        below[0] in self.__block_roles.tree_trunks or
                        below[0] in self.__block_roles.tree_leaves):
                    above = None
                    
                # Extend the surface
                deep = materials.Dirt if self.__block_equal(below, materials.Grass) else below
                self.__replace((x, z, target), initial - target - 1, None, [below, deep])
                if target + 1 < my:
                    # Chop tree base if any shifting up occured
                    top = self.__get_block(local_columns, target + 1)
                    if target > initial and top[0] in self.__block_roles.tree_trunks:
                        # Replace with sapling
                        if not self.__place_sapling((x, z, target + 1), top):
                            self.__place((x, z, target + 1), self.__empty_block(target + 1))
                    
                    # Place supported blocks
                    elif above is not None:
                        self.__place((x, z, target + 1), above)
                    
                self.height[x, z] = target
        
    def remove(self, smoothed, valley_mask=None):
        """ Remove chunk blocks according to provided height map. """

        # Erode blocks based on the height map
        mx, mz, my = self.__local_ids.shape
        removed = numpy.zeros((mx, mz), bool)
        materials = self.__chunk.world.materials
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                local_columns = self.__local_ids[x, z], self.__local_data[x, z]
                target = min(smoothed[x, z], self.height[x, z])
                for n, y in enumerate(xrange(target + 1, my)):
                    curr, curr_data = self.__get_block(local_columns, y)
                    below = int(local_columns[0][y - 1])
                    empty = self.__empty_block(y)
                    
                    # Found a supported block
                    if n == 0 and curr in self.__block_roles.supported and \
                       (below in self.__block_roles.terrain or
                        below in self.__block_roles.tree_trunks or
                        below in self.__block_roles.tree_leaves):
                           
                        # Disolve block if underwater
                        if  empty.ID in self.__block_roles.solvent \
                        and curr in self.__block_roles.disolve:
                            replace = self.__block_roles.disolve[curr]
                            self.__place((x, z, y), empty if replace is None else replace)
                        
                        # Leave block alone
                        else:
                            continue
                    
                    # Eliminate hovering trees but retain the rest
                    elif n > 0 and curr in self.__block_roles.tree_trunks:
                        if below not in self.__block_roles.tree_trunks:
                            # Remove tree trunk
                            self.__place((x, z, y), empty)
                            
                            # Replace with sapling
                            self.__place_sapling((x, z, target + 1), (curr, curr_data))
                    
                    elif curr in self.__block_roles.tree_leaves:
                        # Mark leaves to be updated when the game loads this map
                        self.__local_data[x, z, y] |= 8
                    
                    elif curr in self.__block_roles.tree_trunks:
                        continue
                    
                    # Otherwise remove the block
                    elif curr != empty.ID:
                        top = []
                        
                        # Remove if removable
                        if curr not in self.__block_roles.immutable:
                            # Remember what blocks were previously found at the top
                            if n == 0:
                                by = self.height[x, z]
                                top = [self.__get_block(local_columns, yi)
                                        for yi in xrange(by, by - self.shift_depth, -1)
                                        if yi >= 0]
                                
                                # Disolve top if found to be underwater seabed
                                if empty.ID in self.__block_roles.solvent:
                                    if len(top) > 1 and top[1][0] in self.__block_roles.disolve:
                                        replace = self.__block_roles.disolve[top[1][0]]
                                        if replace is not None:
                                            top[1] = replace
                            
                            # Decide which block to replace current block with
                            if n == 0:
                                new = empty
                                
                                # Move down supported blocks to new height
                                by = self.height[x, z] + 1
                                if by < my:
                                    supported_id = int(local_columns[0][by])
                                    if supported_id in self.__block_roles.supported:
                                        # Find blocks to disolve
                                        if  empty.ID in self.__block_roles.solvent \
                                        and supported_id in self.__block_roles.disolve:
                                            replace = self.__block_roles.disolve[supported_id]
                                            new = empty if replace is None else replace
                                            
                                        # Supported block
                                        else:
                                            # Special case, removing blocks to make shorelines look normal
                                            if y == self.sea_level:
                                                new = empty
                                            
                                            # Supported block retained
                                            else:
                                                new = self.__get_block(local_columns, by)
                            elif y <= self.sea_level and curr in self.__block_roles.water:
                                new = None      # Don't remove water below sea level
                            else:
                                new = empty
                            
                            # Replace current block
                            if new is not None:
                                self.__place((x, z, y), new)
                        
                        # Pretty things up a little where we've stripped things away
                        if n == 0:
                            removed[x, z] = True
                            
                            if y - 1 >= 0:
                                # River bed
                                if valley_mask is not None and y - 1 <= self.sea_level:
                                    self.__replace((x, z, y - 1), -2, None, [materials.Sand])    # River bed
                                
                                # Shift down higher blocks
                                elif top:
                                    self.__replace((x, z, y - 1), -len(top), None, top)
                                
                                # Bare dirt to grass
                                if below == materials.Dirt.ID:
                                    self.__place((x, z, y - 1), materials.Grass)
        
        ### Some improvements can only be made after all the blocks are eroded ###
        
        # Add river water
        if valley_mask is not None:
            for x in xrange(0, mx):
                for z in xrange(0, mz):
                    # Skip if this areas was untouched
                    if not valley_mask[x, z] and not removed[x, z]:
                        continue

                    # Get our bearings
                    y = min(smoothed[x, z], self.height[x, z]) + 1
                        
                    # River water
                    if y <= self.sea_level:
                        self.__replace((x, z, y), self.sea_level - y + 1, None, [materials.Water])  # River water
        
        self.__chunk.Blocks.data = self.__local_ids.data
        self.__chunk.Data.data = self.__local_data.data
        self.__height_invalid = True

    def __inchunk(self, coords):
        """ Check the coordinates are inside the chunk """
        return all(coords[n] >= 0 and coords[n] < self.__local_ids.shape[n] for n in xrange(0, self.__local_ids.ndim))
    
    def __block2pair(self, block):
        """
        If the given block is a material then conver it
        to an (id, data) tuple
        """
        
        if isinstance(block, pymclevel.materials.Block):
            block = (block.ID, block.blockData)
        return block
    
    def __block_equal(self, a, b):
        """ Check if two blocks are the same """
        
        return self.__block2pair(a) == self.__block2pair(b)
    
    def __get_block(self, columns, y):
        # Cast result to int here so the operation is not repeated multiple
        # times causing slow down
        return (int(columns[0][y]), int(columns[1][y]))

    def __place(self, coords, block):
        """ Put the block into the specified coordinates """
        
        self.__local_ids[coords], self.__local_data[coords] = self.__block2pair(block)
    
    def __replace(self, coords, high, from_ids, blocks):
        """
        Replace from_ids blocks (None == any) with specified block starting
        at the given coordinates in a column of specified height.
        """
        
        blocks = ancillary.extend(blocks)
        for y in xrange(coords[2], coords[2] + high, numpy.sign(high)):
            xzy = (coords[0], coords[1], y)
            if not self.__inchunk(xzy):
                return
            if from_ids is None or int(self.__local_ids[xzy]) in from_ids:
                if int(self.__local_ids[xzy]) not in self.__block_roles.immutable:    # Leave immutable blocks alone!
                    self.__place(xzy, blocks.next())
                    
    def __place_sapling(self, coords, tree_trunk):
        """ Place a sappling given a specific tree trunk """
        
        for (a, b), sapling in self.__block_roles.tree_trunks_replace.iteritems():
            tree = self.__block2pair(tree_trunk)
            if a == tree[0] and b & tree[1]:
                self.__place(coords, sapling)
                self.__local_data[coords[0], coords[1], coords[2]] |= 8
                return True
            
        return False
            
    def __around(self, coords, block_ids):
        """ Check if block is surrounded on the sides by specified blocks """
        
        for x, z in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            loc = (coords[0] + x, coords[1] + z, coords[2])
            if self.__inchunk(loc) and self.__local_ids[loc] not in block_ids:
                return False
        return True
    
class Merger(object):
    relight = True
    
    # These form the basis for the height map
    terrain = (
        # Alpha blocks
        'Bedrock', 'BlockofDiamond', 'BlockofGold', 'BlockofIron', 'Brick', 'BrickSlab', 'BrickStairs',
        'Clay', 'CoalOre', 'Cobblestone', 'CobblestoneSlab', 'CrackedStoneBricks', 'DiamondOre', 'Dirt',
        'DoubleBrickSlab', 'DoubleCobblestoneSlab', 'DoubleSandstoneSlab', 'DoubleStoneBrickSlab',
        'DoubleStoneSlab', 'DoubleWoodenSlab', 'Glowstone', 'GoldOre', 'Grass', 'Gravel',
        'HiddenSilverfishCobblestone', 'HiddenSilverfishStone', 'HiddenSilverfishStoneBrick',
        'IronOre', 'LapisLazuliBlock', 'LapisLazuliOre', 'Lava', 'LavaActive', 'MossStone', 'MossyStoneBricks',
        'Mycelium', 'NetherBrick', 'NetherBrickStairs', 'Netherrack', 'Obsidian', 'RedstoneOre',
        'RedstoneOreGlowing', 'Sand', 'Sandstone', 'SandstoneSlab', 'Snow', 'SoulSand', 'Stone',
        'StoneBrickSlab', 'StoneBrickStairs', 'StoneBricks', 'StoneSlab', 'StoneStairs', 'WoodPlanks',
        'WoodenSlab', 'WoodenStairs'
        # Indev
        'InfiniteLava',
        # Pocket
        'Lavaactive',
    )
    
    # These will be retained in place if there is terrain beneath to support them    
    supported = (
        'AprilFoolsChest', 'Bed', 'BirchSapling', 'Bookshelf', 'BrownMushroom', 'Cake', 'Chest',
        'CraftingTable', 'Crops', 'DesertShrub2', 'DetectorRail', 'Dispenser', 'Farmland', 'Fence',
        'FenceGate', 'Flower', 'Furnace', 'Glass', 'GlassPane', 'IronBars', 'IronDoor', 'JackOLantern',
        'Jukebox', 'Lilypad', 'LitFurnace', 'MelonStem', 'MonsterSpawner', 'NetherBrickFence', 'NetherWart',
        'NoteBlock', 'PoweredRail', 'Pumpkin', 'PumpkinStem', 'Rail', 'RedMushroom', 'RedstoneRepeaterOff',
        'RedstoneRepeaterOn', 'RedstoneWire', 'Rose', 'Sapling', 'Shrub', 'Sign', 'SnowLayer', 'Sponge',
        'SpruceSapling', 'StoneFloorPlate', 'TNT', 'TallGrass', 'Trapdoor', 'UnusedShrub', 'Watermelon',
        'Web', 'WoodFloorPlate', 'WoodenDoor'
    )
    
    # These will never be removed
    immutable = (
        'Bedrock',
    )
    
    # These blocks are able to disolve other blocks
    solvent = (
        # Alpha
        'Water', 'WaterActive',
        # Classic
        'InfiniteWater',
        # Pocket
        'Wateractive',
    )
    
    # These blocks will be replaced as specified if underwater (None means completely remove)
    disolve = {
        'Grass': 'Dirt',
        'Lava': 'Obsidian',
        'LavaActive': 'Cobblestone',
        'Mycelium': 'Dirt',
        'Snow': 'Dirt',
        'SnowLayer': None,
    }
    
    # Ignored when reshaping land
    water = (
        # Alpha
        'Ice', 'Water', 'WaterActive',
        # Classic
        'InfiniteWater',
        # Pocket
        'Wateractive',
    )

    # Tree trunks
    tree_trunks = (
        # Alpha
        'BirchWood', 'Cactus', 'HugeBrownMushroom', 'HugeRedMushroom', 'Ironwood', 'SugarCane', 'Vines', 'Wood',
        # Pocket
        'PineWood',
    )
    
    # Leaves and their decayed versions
    tree_leaves = (
        'BirchLeaves', 'BirchLeavesDecaying', 'JungleLeaves', 'JungleLeavesDecaying',
        'Leaves', 'LeavesDecaying', 'PineLeaves', 'PineLeavesDecaying'
    )
    
    # Tree trunk replace
    tree_trunks_replace = {
        # Alpha
        'BirchWood': 'BirchSapling', 'Ironwood': 'SpruceSapling', 'Wood': 'Sapling',
    }
    
    BlockRoleIDs = collections.namedtuple('BlockIDs', ['terrain', 'supported', 'immutable', 'solvent', 'disolve', 'water', 'tree_trunks', 'tree_leaves', 'tree_trunks_replace'])
    
    processing_order = ('even', 'river', 'tidy')
    
    def __init__(self, world_dir, filt_name):
        self.filt_name = filt_name
        
        self.__level = mclevel.fromFile(world_dir)
        self.__block_roles = self.BlockRoleIDs(
            self.__block_material(self.terrain),
            self.__block_material(self.supported),
            self.__block_material(self.immutable),
            self.__block_material(self.solvent),
            self.__block_material(self.disolve, ('ID', ('ID', 'blockData'))),
            self.__block_material(self.water),
            self.__block_material(self.tree_trunks),
            self.__block_material(self.tree_leaves),
            self.__block_material(self.tree_trunks_replace, (('ID', 'blockData'), None))
        )
        
        self.log_interval = 1
        self.log_function = None
    
    def __block_material(self, names, attrs='ID'):
        """
        Returns block attributes for those names that are present in the loaded level materials.
        Attemps to retain the original structure of the input set.
        """
        
        def cycle(it):
            if it is None or isinstance(it, basestring):
                return itertools.repeat(it)
            else:
                return itertools.cycle(it)
        
        def getter(attrs):
            if attrs is None:
                return lambda obj: obj
            elif isinstance(attrs, basestring):
                return lambda obj: None if obj is None else getattr(obj, attrs)
            else:
                return lambda obj: None if obj is None else tuple(None if attr is None else getattr(obj, attr) for attr in attrs)
            
        def hasattr_or_none(obj, name):
            return True if name is None else hasattr(obj, name)
        
        def getattr_or_none(obj, name):
            return None if name is None else getattr(obj, name)
        
        materials = self.__level.materials
        if hasattr_or_none(names, 'iteritems'):
            atrs = [getter(attr) for attr in itertools.islice(cycle(attrs), 2)]
            return dict([atrs[i](getattr_or_none(materials, n)) for i, n in enumerate(ns)]
                        for ns in names.iteritems()
                        if all(hasattr_or_none(materials, n) for n in ns))
        else:
            atr = getter(attrs)
            return set(atr(getattr_or_none(materials, n)) for n in names if hasattr_or_none(materials, n))
    
    def __have_surrounding(self, coords, radius):
        """ Check if all surrounding chunks are present """
        
        range = (-radius, radius+1)
        for z in xrange(*range):
            for x in xrange(*range):
                if (coords[0] + x, coords[1] + z) not in self.__level.allChunks:
                    return False
        return True
    
    def erode(self, contour):
        # Requisite objects
        height_map = contour.height_map(self.__level, self.__block_roles)
        
        # Go through each processing method in turn
        reshaped = {}; n = 0
        for method in self.processing_order:
            method_bit = Contour.methods[method].bit
            reshaped[method] = []
            
            # Go through all the chunks that require processing
            for coord in (k for k, v in contour.edges.iteritems() if v.method & method_bit != 0):
                # Progress logging
                if self.log_function is not None:
                    if n % self.log_interval == 0:
                        self.log_function(n)

                # We only re-shape when surrounding chunks are present to prevent river spillage
                # and ensure padding requirements can be fulfilled
                if self.__have_surrounding(coord, filter.padding):
                    cs = ChunkShaper(self.__level.getChunk(*coord), contour, height_map, self.__block_roles)
                    cs.reshape(method, self.filt_name)
                    reshaped[method].append(coord)
                    height_map.invalidations.add(coord)
                
                # Count relevant chunks
                n += 1
            
            # Height map must be invalidated between stages
            height_map.invalidate_deferred()
        
        # Do final logging update for the end
        if self.log_function is not None:
            self.log_function(n)
        
        return reshaped
    
    def commit(self):
        """ Finalise and save map """
        
        if self.relight:
            self.__level.generateLights()
        self.__level.saveInPlace()

