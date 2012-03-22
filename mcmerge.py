import sys, pickle, os.path, itertools, collections, errno, getopt, logging
import numpy
from pymclevel import mclevel
import pymclevel.materials
import ancillary, vec, carve, filter
from contour import Contour, ContourLoadError, HeightMap
from carve import ChunkSeed

logging.basicConfig(format="... %(message)s")
pymclevel_log = logging.getLogger('pymclevel')
pymclevel_log.setLevel(logging.CRITICAL)

version = '0.5.3'

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
    
    def __init__(self, chunk, contour, height_map, block_roles):
        """ Takes a pymclevel chunk as an initialiser """
        
        self.__block_roles = block_roles
        self.__chunk = chunk
        self.__contour = contour
        self.__height_map = height_map
        self.__edge = contour.edges[self.__chunk.chunkPosition]
        self.__edge_direction = [numpy.array(v) for v in self.__edge.direction]
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
    
    def reshape(self, filt_name, filt_factor):
        """ Reshape the original chunk to the smoothed out result """
        
        self.__ocean = bool(self.__edge.method & Contour.methods['ocean'].bit)
            
        changed = False
        for method in ['average', 'river']:   # This defines the order of processing
            if self.__edge.method & Contour.methods[method].bit:
                self.__shape(method, filt_name, filt_factor)
                changed = True
                
        if changed:
            self.__chunk.chunkChanged()
        
    def __shape(self, method, filt_name, filt_factor):
        """ Does the reshaping work for a specific shaping method """
        
        if method == 'river':
            smoothed, erode_mask = self.erode_valley(filt_name, filt_factor)
            self.remove(smoothed, erode_mask)
        elif method == 'average':
            smoothed = self.erode_slope(filt_name, filt_factor)
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
        mx, mz = self.height.shape
        materials = self.__chunk.world.materials
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                # Get target height, make sure it's in the chunk
                target = max(smoothed[x, z], self.height[x, z])
                if target > self.__local_ids.shape[2] - 1:
                    target = self.__local_ids.shape[2] - 1
                    
                # Collect details about blocks on the surface
                initial = self.height[x, z]
                below = self.__get_block((x, z, initial))
                if self.__inchunk((x, z, initial + 1)):
                    above = self.__get_block((x, z, initial + 1))
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
                if target + 1 < self.__local_ids.shape[2]:
                    # Chop tree base if any shifting up occured
                    top = self.__get_block((x, z, target + 1))
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
        mx, mz = self.height.shape
        removed = numpy.zeros((mx, mz), bool)
        materials = self.__chunk.world.materials
        for x in xrange(0, mx):
            for z in xrange(0, mz):
                target = min(smoothed[x, z], self.height[x, z])
                for n, y in enumerate(xrange(target + 1, self.__local_ids.shape[2])):
                    curr, curr_data = self.__get_block((x, z, y))
                    below = self.__local_ids[x, z, y - 1]
                    empty = self.__empty_block(y)
                    
                    # Found a supported block
                    if n == 0 and curr in self.__block_roles.supported and \
                       (below in self.__block_roles.terrain or
                        below in self.__block_roles.tree_trunks or
                        below in self.__block_roles.tree_leaves):
                           
                        # Disolve block if underwater
                        empty = self.__empty_block(y)
                        
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
                            self.__place((x, z, y), self.__empty_block(y))
                            
                            # Replace with sapling
                            self.__place_sapling((x, z, target + 1), (curr, curr_data))
                    
                    elif curr in self.__block_roles.tree_leaves:
                        # Mark leaves to be updated when the game loads this map
                        self.__local_data[x, z, y] |= 8
                    
                    elif curr in self.__block_roles.tree_trunks:
                        continue
                    
                    # Otherwise remove the block
                    elif curr != self.__empty_block(y).ID:
                        top = []
                        
                        # Remove if removable
                        if curr not in self.__block_roles.immutable:
                            # For efficiency
                            if n == 0:
                                empty = self.__empty_block(y)
                                
                            # Remember what blocks were previously found at the top
                            if n == 0:
                                by = self.height[x, z]
                                top = [self.__get_block((x, z, yi))
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
                                if by < self.__local_ids.shape[2]:
                                    supported_id = self.__local_ids[x, z, by]
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
                                                new = self.__get_block((x, z, by))
                            elif y <= self.sea_level and curr in self.__block_roles.water:
                                new = None      # Don't remove water below sea level
                            else:
                                new = self.__empty_block(y)
                            
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
                                below = self.__local_ids[x, z, y - 1]
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
                    below = self.__local_ids[x, z, y - 1]
                        
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
    
    def __get_block(self, coords):
        return (self.__local_ids[coords[0], coords[1], coords[2]],
                self.__local_data[coords[0], coords[1], coords[2]])

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
            if from_ids is None or self.__local_ids[xzy] in from_ids:
                if self.__local_ids[xzy] not in self.__block_roles.immutable:    # Leave immutable blocks alone!
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
    
class Shifter(object):
    """
    Shifts areas of the map up or down.
    """
    
    relight = True
    
    def __init__(self, world_dir):
        self.__level = mclevel.fromFile(world_dir)
        
        self.log_interval = 1
        self.log_function = None
    
    @property
    def level(self):
        return self.__level
    
    def shift(self, distance):
        # Calculate shift coordinates
        height = self.__level.Height
        if distance == 0:
            return
        elif distance < 0:
            yfrom = (1 - distance, height)
            yto = (1, height + distance)
            ybuffer = (height + distance, height)
        elif distance > 0:
            yfrom = (1, height - distance)
            yto = (1 + distance, height)
            ybuffer = (1, 1 + distance)
        
        # Go through all the chunks and data around
        for n, coord in enumerate(self.__level.allChunks):
            # Progress logging
            if self.log_function is not None:
                if n % self.log_interval == 0:
                    self.log_function(n)
            
            chunk = self.__level.getChunk(*coord)
            for arr in (chunk.Blocks, chunk.Data, chunk.BlockLight, chunk.SkyLight):
                # Do the shifting
                arr[:, :, yto[0]:yto[1]] = arr[:, :, yfrom[0]:yfrom[1]]
            
                # Fill in gaps
                copy_volume = arr.shape[0]*arr.shape[1]*(ybuffer[1] - ybuffer[0])
                copy_edges = (arr.shape[0], arr.shape[1], ybuffer[1] - ybuffer[0])
                if distance < 0:
                    # For top of map we want to fill with air blocks
                    custom = ((chunk.Blocks, chunk.world.materials.Air.ID), (chunk.Blocks, chunk.world.materials.Air.blockData))
                    for which, val in custom:
                        if arr is which:
                            arr[:, :, ybuffer[0]:ybuffer[1]] = numpy.fromiter(itertools.repeat(val, copy_volume), arr.dtype).reshape(copy_edges)
                            break
                    
                    # Just copy the lighting data from the top most row, this is probably bad...
                    else:
                        arr[:, :, ybuffer[0]:ybuffer[1]] = numpy.fromiter(itertools.islice(itertools.cycle(arr[:, :, height-1:height].flatten()), copy_volume), arr.dtype).reshape(copy_edges)
                else:
                    # Copy all data from the bottom row
                    arr[:, :, ybuffer[0]:ybuffer[1]] = numpy.fromiter(itertools.islice(itertools.cycle(arr[:, :, 0:1].flatten()), copy_volume), arr.dtype).reshape(copy_edges)
                        
            # Shift all entity positions
            for entity in chunk.Entities:
                entity['Pos'][1].value += distance
            
            # Shift all tile entity positions
            for entity in chunk.TileEntities:
                entity['y'].value += distance
                
            # The chunk has changed!
            chunk.chunkChanged()
        
        def shiftY(coord, distance):
            return [coord[0], coord[1] + distance, coord[2]]
        
        # Shift all player positions and spawns
        for player in self.__level.players:
            self.__level.setPlayerSpawnPosition(shiftY(self.__level.playerSpawnPosition(player), distance), player)
            self.__level.setPlayerPosition(shiftY(self.__level.getPlayerPosition(player), distance), player)
        
        # Shift default spawn position
        self.__level.setPlayerSpawnPosition(shiftY(self.__level.playerSpawnPosition(), distance))
        
        # Do final logging update for the end
        if self.log_function is not None:
            self.log_function(n + 1)
        
        return n + 1
        
    def commit(self):
        """ Finalise and save map """
        
        if self.relight:
            self.__level.generateLights()
        self.__level.saveInPlace()

class Relighter(object):
    """
    Relight chunks so we don't get dark patches
    after making alterations to the map.
    """
    
    def __init__(self, world_dir):
        self.__level = mclevel.fromFile(world_dir)
        
        self.log_interval = 1
        self.log_function = None
    
    @property
    def level(self):
        return self.__level
    
    def relight(self):
        # Go through all chunks
        for n, coord in enumerate(self.__level.allChunks):
            # Progress logging
            if self.log_function is not None:
                if n % self.log_interval == 0:
                    self.log_function(n)
            
            # Mark for relighting
            self.__level.getChunk(*coord).chunkChanged()
        
        # Do final logging update for the end
        if self.log_function is not None:
            self.log_function(n + 1)
        
        # Now pymclevel does the relighting work
        self.__level.generateLights()
        
        return n + 1
        
    def commit(self):
        """ Finalise and save map """
        
        self.__level.saveInPlace()

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
    
    def __init__(self, world_dir, filt_name, filt_factor):
        self.filt_name = filt_name
        self.filt_factor = filt_factor
        
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
        
        # Go through all the chunks that require smoothing
        reshaped = []
        for n, coord in enumerate(contour.edges.iterkeys()):
            # Progress logging
            if self.log_function is not None:
                if n % self.log_interval == 0:
                    self.log_function(n)

            # We only re-shape when surrounding chunks are present to prevent river spillage
            # and ensure padding requirements can be fulfilled
            if self.__have_surrounding(coord, filter.padding):
                cs = ChunkShaper(self.__level.getChunk(*coord), contour, height_map, self.__block_roles)
                cs.reshape(self.filt_name, self.filt_factor)
                reshaped.append(coord)
        
        # Do final logging update for the end
        if self.log_function is not None:
            self.log_function(n + 1)
        
        return reshaped
    
    def commit(self):
        """ Finalise and save map """
        
        if self.relight:
            self.__level.generateLights()
        self.__level.saveInPlace()

if __name__ == '__main__':
    # Define some defaults
    contour_file_name = 'contour.dat'
    filt_factor = 1.7
    filt_name = 'smooth'
    shift_down = 1
    
    class Modes(object):
        __metaclass__ = ancillary.Enum
        __elements__ = ['trace', 'shift', 'merge', 'relight']
    
    # Helpful usage information
    def usage():
        print "Usage: %s <mode> [options] <world_dir>" % os.path.basename(sys.argv[0])
        print
        print "Stitches together existing Minecraft map regions with newly generated areas"
        print "by separating them with a river."
        print
        print "Uses a two phase process. First trace out the contour of the original map"
        print "with the 'trace' mode. After generating the new areas, stitch them together"
        print "by running in the 'merge' mode. The stitching phase may be executed multiple"
        print "times if not all new chunks bordering with the old map are available."
        print
        print "An optional additional phase is available to shift the sea-level of the map. It"
        print "can be done before the other phases using the 'shift' mode. It is only necessary"
        print "if moving between version 1.7 (or earlier) to verion 1.8 (or later) maps."
        print
        print "Modes:"
        print "  shift          shifts the map height up or down"
        print "  trace          generates contour data for the original world before"
        print "                 new areas are added"
        print "  merge          merges and smooths the old and new areas together using the"
        print "                 data collected in the trace phase"
        print "  relight        relights all chunks in the world without doing anything"
        print "                 else, note that other modes do this automatically"
        print 
        print "Options:"
        print "-h, --help                    displays this help"
        print "    --version                 prints the version number"
        print
        print "-d  --shift-down=<val>        number of blocks to shift the map down by, this"
        print "                              may be negative to shift up instead, default: %d" % shift_down
        print
        print "-c, --contour=<file_name>     file that records the contour data in the"
        print "                              world directory, default: %s" % contour_file_name
        print "    --no-relight              don't do relighting in modes that do this by"
        print "                              default, this is faster but leaves dark areas"
        print
        print "-s, --smooth=<factor>         smoothing filter factor, default: %.2f" % filt_factor
        print "-f, --filter=<filter>         name of filter to use, default: %s" % filt_name
        print "                              available: %s" % ', '.join(filter.filters.iterkeys())
        print "-r, --river-width=<val>       width of the river, default: %d" % (ChunkShaper.river_width*2)
        print "-v, --valley-width=<val>      width of the valley, default: %d" % (ChunkShaper.valley_width*2)
        print "    --river-height=<val>      y co-ord of river bottom, default: %d" % ChunkShaper.river_height
        print "    --valley-height=<val>     y co-ord of valley bottom, default: %d" % ChunkShaper.valey_height
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
        print "    --cover-depth=<val>       depth of blocks transferred from original surface"
        print "                              to carved out valley bottom, default: %d" % ChunkShaper.shift_depth
    
    def error(msg):
        print "For usage type: %s --help" % os.path.basename(sys.argv[0])
        print
        print "Error: %s" % msg
        sys.exit(1)
    
    # Parse parameters
    try:
        opts, args = getopt.gnu_getopt(
            sys.argv[1:],
            "hs:f:c:d:r:v:",
            ['help', 'version', 'shift-down=', 'smooth=', 'filter=',
             'contour=', 'river-width=', 'valley-width=', 'river-height=',
             'valley-height=', 'river-centre-deviation=',
             'river-width-deviation=', 'river-centre-bend=',
             'river-width-bend=','sea-level=', 'narrow-factor=',
             'cover-depth=', 'no-relight']
        )

    except getopt.GetoptError, e:
        error(e)
    
    if any(opt in ('-h', '--help') for opt, _ in opts):
        usage()
        sys.exit(0)

    if any(opt in ('--version',) for opt, _ in opts):
        print "mcmerge v%s" % version
        sys.exit(0)
    
    if len(args) < 1:
        error("must specify usage mode")
    elif len(args) < 2:
        error("must provide world directory location")
    elif len(args) > 2:
        error("only one world location may be specified")
    else:
        world_dir = args[1]
    
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
    
    # Determine the mode, accepts word abbreviations
    mode = None
    for e in Modes():
        if str(e).startswith(args[0].lower()):
            if mode is None:
                mode = e
            else:
                error("ambiguous mode name '%s', please provide full name" % args[0])
                
    if mode is None:
        error("unrecognised mode '%s'" % args[0])
    
    # Get options
    for opt, arg in opts:
        if opt in ('-d', '--shift-down'):
            shift_down = get_int(arg, 'shift down')
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
            cover_depth = get_int(arg, 'cover depth')
            if cover_depth < 0:
                cover_depth = 0
            ChunkShaper.shift_depth = cover_depth
        elif opt == '--no-relight':
            Shifter.relight = False
            Merger.relight = False

    def error(msg):
        print "Error: %s" % msg
        sys.exit(1)
        
    # Trace contour of the old world
    if mode is Modes.trace:
        print "Finding world contour..."
        contour = Contour()
        try:
            contour.trace_world(world_dir)
        except (EnvironmentError, ContourLoadError), e:
            error('could not read world contour: %s' % e)
        
        print "Recording world contour..."
        try:
            contour.write(os.path.join(world_dir, contour_file_name))
        except EnvironmentError, e:
            error('could not write world contour data: %s' % e)
        
        print "World contour detection complete"
    
    # Shift the map height
    elif mode is Modes.shift:
        print "Loading world..."
        
        try:
            shift = Shifter(world_dir)
        except EnvironmentError, e:
            error('could not read world data: %s' % e)
        
        print "Shifting chunks:"
        print
        
        total = sum(1 for _ in shift.level.allChunks)
        width = len(str(total))
        def progress(n):
            print ("... %%%dd/%%d (%%.1f%%%%)" % width) % (n, total, 100.0*n/total)
        shift.log_interval = 200
        shift.log_function = progress
        shifted = shift.shift(-shift_down)
        
        print
        print "Relighting and saving:"
        print
        pymclevel_log.setLevel(logging.INFO)
        try:
            shift.commit()
        except EnvironmentError, e:
            error('could not save world data: %s' % e)
        pymclevel_log.setLevel(logging.CRITICAL)
        
        print
        print "Finished shifting, shifted: %d chunks" % shifted

    # Attempt to merge new chunks with old chunks
    elif mode is Modes.merge:
        contour_data_file = os.path.join(world_dir, contour_file_name)
        
        if filt_name == 'gauss':
            if not hasattr(filter, 'scipy'):
                print "You must install SciPy to use this filter"
                sys.exit(1)
        
        print "Getting saved world contour..."
        contour = Contour()
        try:
            contour.read(contour_data_file)
        except (EnvironmentError, ContourLoadError), e:
            if e.errno == errno.ENOENT:
                if os.path.exists(world_dir):
                    error("no contour data to merge with (use trace mode to generate)")
                else:
                    error('could not read world data: File not found: %s' % world_dir)
            else:
                error('could not read contour data: %s' % e)
        
        print "Loading world..."
        print
        
        try:
            merge = Merger(world_dir, filt_name, filt_factor)
        except EnvironmentError, e:
            error('could not read world data: %s' % e)
        
        print "Merging chunks:"
        print
        
        total = len(contour.edges)
        width = len(str(total))
        def progress(n):
            print ("... %%%dd/%%d (%%.1f%%%%)" % width) % (n, total, 100.0*n/total)
        merge.log_interval = 10
        merge.log_function = progress
        reshaped = merge.erode(contour)
        
        print
        print "Relighting and saving:"
        print
        pymclevel_log.setLevel(logging.INFO)
        try:
            merge.commit()
        except EnvironmentError, e:
            error('could not save world data: %s' % e)
        pymclevel_log.setLevel(logging.CRITICAL)
        
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
            error('could not updated world contour data: %s' % e)
            
    # Relight all the chunks on the map
    elif mode is Modes.relight:
        print "Loading world..."
        
        try:
            relight = Relighter(world_dir)
        except EnvironmentError, e:
            error('could not read world data: %s' % e)
        
        print "Marking and relighting chunks:"
        print
        
        pymclevel_log.setLevel(logging.INFO)
        relit = relight.relight()
        
        print
        print "Saving:"
        print
        
        try:
            relight.commit()
        except EnvironmentError, e:
            error('could not save world data: %s' % e)
        pymclevel_log.setLevel(logging.CRITICAL)
        
        print
        print "Finished relighting, relit: %d chunks" % relit
    
    # Should have found the right mode already!
    else:
        error("something went horribly wrong performing mode '%s'" % mode)
