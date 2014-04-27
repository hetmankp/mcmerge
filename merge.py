import itertools, collections
import numpy
from pymclevel import mclevel
import pymclevel.materials
import ancillary, carve, filter, vec
from contour import Contour, HeightMap, EdgeData
from carve import ChunkSeed

# TODO: Split this class into two separate classes. One purely for doing the practical work of reshaping an actual chunk,
#       and another to plan the contour reshaping heights. The planner could eventually become more flexible having the
#       knowledge of multiple surrounding chunks.
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
    
    filt_name_river = 'smooth'
    filt_factor_river = 1.7
    filt_name_even = 'gauss'
    filt_factor_even = 1.0
    
    def __init__(self, chunk, edge, padding, height_map, block_roles):
        """ Takes a pymclevel chunk as an initialiser """
        
        self.__block_roles = block_roles
        self.__chunk = chunk
        self.__height_map = height_map
        self.__edge = edge
        self.__edge_direction = vec.tuples2vecs(self.__edge.direction)
        self.__desert = False
        self.__ocean = False
        self.__dry = False
        self.__local_ids = chunk.Blocks.copy()
        self.__local_data = chunk.Data.copy()
        self.__seeder = ChunkSeed(chunk.world.RandomSeed, chunk.chunkPosition)
        self.__padding = padding
        
        self.__height_invalid = True
        self.height     # Initialise the height value
        
    @staticmethod
    def filt_is_river(name):
        return name == 'river'
    
    @staticmethod
    def filt_is_even(name):
        return name in ('even', 'tidy')
        
    @property
    def height(self):
        if self.__height_invalid:
            self.__height = HeightMap.find_heights(self.__local_ids, self.__block_roles)
            self.__height_invalid = False
            
        return self.__height
    
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
    
    def reshape(self, method):
        """ Reshape the original chunk to the smoothed out result """
        
        if self.__edge.method & Contour.methods[method].bit:
            self.__desert = bool(self.__edge.method & Contour.methods['desert'].bit)
            self.__ocean = bool(self.__edge.method & Contour.methods['ocean'].bit)
            self.__dry = bool(self.__edge.method & Contour.methods['dry'].bit)
            self.__shape(method)
            self.__chunk.chunkChanged()
        
    def __shape(self, method):
        """ Does the reshaping work for a specific shaping method """
        
        if self.filt_is_river(method):
            smoothed, erode_mask = self.erode_valley(self.filt_name_river, self.filt_factor_river)
            self.remove(smoothed, erode_mask)
        elif self.filt_is_even(method):
            smoothed = self.erode_slope(self.filt_name_river, self.filt_factor_even)
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
        
        return numpy.cast[self.height.dtype](numpy.round(ffun(self.height, filt_factor, self.chunk_padder, self.__padding)))
    
    def erode_valley(self, filt_name, filt_factor):
        """
        Produced a smoothed version of the original height map with a
        river valley added around the marked edge.
        """
        
        ffun = getattr(filter, filter.filters[filt_name])
        
        valley, erode_mask = self.with_valley(self.height)
        carved = self.with_river(valley)
        return numpy.cast[carved.dtype](numpy.round(ffun(carved, filt_factor, filter.pad, self.__padding))), erode_mask
    
    def chunk_padder(self, a, padding):
        """
        Pads the chunk heigh map array 'a' with surrounding chunks
        from the source world.
        """
            
        single_size = a.shape
        padded_size = tuple(x*(padding*2+1) for x in single_size)
        b = numpy.empty(padded_size, a.dtype)
        
        range = (-padding, padding+1)
        coords = self.__chunk.chunkPosition
        
        # First fill in the surrounding land
        for z in xrange(*range):
            for x in xrange(*range):
                if z == 0 and x == 0:
                    continue
                
                xoffset = (x + padding)*single_size[0]
                zoffset = (z + padding)*single_size[1]
                cheight = self.__height_map[(coords[0] + x, coords[1] + z)]
                b[xoffset:xoffset+single_size[0], zoffset:zoffset+single_size[1]] = cheight
                
        # Finally add the data being padded
        xoffset = (0 + padding)*single_size[0]
        zoffset = (0 + padding)*single_size[1]
        b[xoffset:xoffset+single_size[0], zoffset:zoffset+single_size[1]] = a
        
        return b
    
    def __empty_block(self, height=0):
        """ Returns block corresponding to emptiness """
        
        if self.__ocean and height <= self.sea_level:
            return self.__chunk.world.materials.Water
        else:
            return self.__chunk.world.materials.Air
    
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
                above = self.__get_block(local_columns, initial + 1) if initial + 1 < my else None
                supported_layer = self.__supported_blocks(local_columns, x, z, initial, below[0])
                
                # Extend the surface
                deep = materials.Dirt if self.__block_equal(below, materials.Grass) else below
                self.__replace((x, z, target), initial - target - 1, None, [below, deep])
                if target + 1 < my:
                    # Chop tree base if any shifting up occured
                    top = self.__get_block(local_columns, target + 1)
                    if  target > initial \
                    and above[0] in self.__block_roles.tree_trunks \
                    and top[0] not in self.__block_roles.tree_trunks:
                        # Replace with sapling
                        if not self.__place_sapling((x, z, target + 1), above):
                            self.__place((x, z, target + 1), self.__empty_block(target + 1))
                    
                    # Place supported blocks
                    else:
                        for i, block in enumerate(supported_layer):
                            self.__place((x, z, target + i + 1), block)
                    
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
                initial = self.height[x, z]
                target = min(smoothed[x, z], self.height[x, z])
                
                below = self.__get_block(local_columns, initial)
                top_layer = [self.__get_block(local_columns, yi)
                             for yi in xrange(initial, initial - self.shift_depth, -1)
                             if yi >= 0]
                supported_layer = self.__supported_blocks(local_columns, x, z, initial, below[0])
                
                for n, y in enumerate(xrange(target + 1, my)):
                    curr_id, curr_data = self.__get_block(local_columns, y)
                    empty = self.__empty_block(y)
                    
                    # Eliminate hovering trees but retain the rest
                    if n > 0 and curr_id in self.__block_roles.tree_trunks:
                        under_id = int(local_columns[0][y - 1])
                        if under_id not in self.__block_roles.tree_trunks:
                            # Remove tree trunk
                            self.__place((x, z, y), empty)
                            
                            # Replace with sapling if this looks like the main tree trunk
                            if y + 1 < my and (curr_id, curr_data) == self.__get_block(local_columns, y + 1):
                                if not self.__place_sapling((x, z, target + 1), (curr_id, curr_data)):
                                    self.__place((x, z, target + 1), self.__empty_block(target + 1))
                    
                    elif curr_id in self.__block_roles.update:
                        # Mark leaves to be updated when the game loads this map
                        self.__local_data[x, z, y] |= 8
                    
                    elif curr_id in self.__block_roles.tree_trunks:
                        continue
                    
                    # Otherwise remove the block
                    elif curr_id != empty.ID:
                        # Remove if removable
                        if curr_id not in self.__block_roles.immutable:
                            # Decide which block to replace current block with
                            if n < len(supported_layer):
                                supported_id = supported_layer[n]
                                
                                # Find supported blocks to disolve
                                if  empty.ID in self.__block_roles.solvent \
                                and supported_id in self.__block_roles.disolve:
                                    replace = self.__block_roles.disolve[supported_id]
                                    new = empty if replace is None else replace
                                    
                                # Don't dissolve supported block
                                else:
                                    # Special case, removing blocks to make shorelines look normal
                                    if y == self.sea_level:
                                        new = empty
                                    
                                    # Supported block retained
                                    else:
                                        new = self.__get_block(local_columns, initial + 1)
                                
                                # Supported blocks must always be on other supporting blocks
                                if new is empty:
                                    supported_layer = supported_layer[0:n]
                            elif not self.__desert and y <= self.sea_level and curr_id in self.__block_roles.water:
                                new = None      # Don't remove water below sea level except in deserts
                            else:
                                new = empty
                            
                            # Replace current block
                            if new is not None:
                                self.__place((x, z, y), new)
                        else:
                            new = None
                        
                        # Extra work if first layer
                        if n == 0:
                            # Disolve top block in top layer if found to be underwater
                            if (curr_id if new is None else new) in self.__block_roles.solvent:
                                if len(top_layer) > 0 and top_layer[0][0] in self.__block_roles.disolve:
                                    replace = self.__block_roles.disolve[top_layer[0][0]]
                                    if replace is not None:
                                        top_layer[0] = replace
                        
                            # Pretty things up a little where we've stripped things away
                            removed[x, z] = True
                            
                            if y - 1 >= 0:
                                # River bed
                                if valley_mask is not None and y - 1 <= self.sea_level:
                                    self.__replace((x, z, y - 1), -2, None, [materials.Sand])    # River bed
                                
                                # Shift down higher blocks
                                elif top_layer:
                                    self.__replace((x, z, y - 1), -len(top_layer), None, top_layer)
                                
                                # Bare dirt to grass
                                if below[0] == materials.Dirt.ID:
                                    self.__place((x, z, y - 1), materials.Grass)
        
        ### Some improvements can only be made after all the blocks are eroded ###
        
        # Add river water
        riverbed_material = [materials.Air if self.__dry else materials.Water]
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
                        self.__replace((x, z, y), self.sea_level - y + 1, None, riverbed_material)  # River water
        
        self.__chunk.Blocks.data = self.__local_ids.data
        self.__chunk.Data.data = self.__local_data.data
        self.__height_invalid = True

    def __supported_blocks(self, local_columns, x, z, y_top, below_id):
        """Only supported blocks will be kept on the new surface"""
        
        above = []
        if self.__inchunk((x, z, y_top + 1)):
            block = self.__get_block(local_columns, y_top + 1)
            if block[0] in self.__block_roles.supported \
                    and (below_id in self.__block_roles.terrain or
                         below_id in self.__block_roles.tree_trunks or
                         below_id in self.__block_roles.tree_leaves):
                above.append(block)
                if self.__inchunk((x, z, y_top + 2)):
                    block = self.__get_block(local_columns, y_top + 2)
                    if block[0] in self.__block_roles.supported2:
                        above.append(block)
        
        return above
                
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
        
        tree = self.__block2pair(tree_trunk)
        for (a, b), sapling in self.__block_roles.tree_trunks_replace.iteritems():
            if a == tree[0] and b == (tree[1] & 0x7):
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
    
    filt_radius_even = 1
    filt_padding_even = 2
    filt_radius_river = 0
    filt_padding_river = 1
    
    # We do not name individual blocks with the same IDs but different block data,
    # in the following cases:
    #   Wheat, Sandstone, Wood Planks, Flower, Large Flowers, etc.
    
    # Unused block types (only here for documentation)
    unused = (
        # Alpha blocks
        'Acacia Placeholder Wood (Bark Only)',
        'Acacia Placeholder Wood (East/West)',
        'Acacia Placeholder Wood (North/South)',
        'Acacia Placeholder Wood (Upright)',
        'Acacia Wood (Bark Only)',
        'Air',
        'Barrier',
        'Birch Wood (Bark Only)',
        'Black Wool',
        'Blue Wool',
        'Brown Wool',
        'Cocoa Plant',
        'Cyan Wool',
        'Dark Oak Placeholder Wood (Bark Only)',
        'Dark Oak Placeholder Wood (East/West)',
        'Dark Oak Placeholder Wood (North/South)',
        'Dark Oak Placeholder Wood (Upright)',
        'Dark Oak Wood (Bark Only)',
        'End Portal Frame',
        'Fire',
        'Gray Wool',
        'Green Wool',
        'Hay Block',
        'Huge Brown Mushroom',
        'Huge Brown Mushroom (East)',
        'Huge Brown Mushroom (North)',
        'Huge Brown Mushroom (Northeast)',
        'Huge Brown Mushroom (Northwest)',
        'Huge Brown Mushroom (South)',
        'Huge Brown Mushroom (Southeast)',
        'Huge Brown Mushroom (Southwest)',
        'Huge Brown Mushroom (Stem)',
        'Huge Brown Mushroom (Top)',
        'Huge Brown Mushroom (West)',
        'Huge Red Mushroom',
        'Huge Red Mushroom (East)',
        'Huge Red Mushroom (North)',
        'Huge Red Mushroom (Northeast)',
        'Huge Red Mushroom (Northwest)',
        'Huge Red Mushroom (South)',
        'Huge Red Mushroom (Southeast)',
        'Huge Red Mushroom (Southwest)',
        'Huge Red Mushroom (Stem)',
        'Huge Red Mushroom (Top)',
        'Huge Red Mushroom (West)',
        'Jungle Wood (Bark Only)',
        'Ladder',
        'Lever',
        'Light Blue Wool',
        'Light Gray Wool',
        'Lime Wool',
        'Magenta Wool',
        'Nether Portal',
        'Oak Wood (Bark Only)',
        'Orange Wool',
        'Pink Wool',
        'Piston',
        'Piston Head',
        'Piston Movement Placeholder',
        'Purple Wool',
        'Red Wool',
        'Redstone Torch (Off)',
        'Redstone Torch (On)',
        'Slime Block',
        'Spruce Wood (Bark Only)',
        'Sticky Piston',
        'Stone Button',
        'Torch',
        'Tripwire',
        'Tripwire Hook',
        'Wall Sign',
        'White Wool',
        'Wooden Button',
        'Yellow Wool',
        
        # Indev/classic
        'Aqua Wool',
        'Indigo Wool',
        'Violet Wool',
        
        # Indev
        'Cog',
        
        # Pocket
        'Error Grass',
        'Error Leaves',
        'Error Stone',
    )
    
    # These form the basis for the height map
    terrain = (
        # Alpha blocks
        'Acacia Wood Slab',
        'Acacia Wood Stairs',
        'Andesite',
        'Bedrock',
        'Birch Wood Slab',
        'Birch Wood Stairs',
        'Block of Coal',
        'Block of Diamond',
        'Block of Emerald',
        'Block of Gold',
        'Block of Iron',
        'Block of Quartz',
        'Block of Redstone',
        'Brick',
        'Brick Slab',
        'Brick Slab (Upper)',
        'Brick Stairs',
        'Chiseled Stone Bricks',
        'Clay',
        'Coal Ore',
        'Cobblestone',
        'Cobblestone Slab',
        'Cobblestone Slab (Upper)',
        'Cobblestone Stairs',
        'Cracked Stone Bricks',
        'Dark Oak Wood Slab',
        'Dark Oak Wood Stairs',
        'Diamond Ore',
        'Diorite',
        'Dirt',
        'Double Acacia Wood Slab',
        'Double Birch Wood Slab',
        'Double Brick Slab',
        'Double Cobblestone Slab',
        'Double Dark Oak Wood Slab',
        'Double Jungle Wood Slab',
        'Double Oak Wood Slab',
        'Double Nether Brick Slab',
        'Double Quartz Slab',
        'Double Sandstone Slab',
        'Double Spruce Wood Slab',
        'Double Stone Brick Slab',
        'Double Stone Slab',
        'Double Wooden Slab (Old)',
        'Emerald Ore',
        'End Stone',
        'Glowstone',
        'Gold Ore',
        'Granite',
        'Grass',
        'Grassless Dirt',
        'Gravel',
        'Hardened Clay',
        'Silverfish Block (Chiseled Stone Bricks)',
        'Silverfish Block (Cobblestone)',
        'Silverfish Block (Cracked Stone Bricks)',
        'Silverfish Block (Mossy Stone Bricks)',
        'Silverfish Block (Smooth Stone)',
        'Silverfish Block (Stone Bricks)',
        'Iron Ore',
        'Jungle Wood Slab',
        'Jungle Wood Stairs',
        'Lapis Lazuli Block',
        'Lapis Lazuli Ore',
        'Lava',
        'Lava (Flowing)',
        'Moss Stone',
        'Mossy Stone Bricks',
        'Mycelium',
        'Nether Brick',
        'Nether Brick Slab',
        'Nether Brick Slab (Upper)',
        'Nether Quartz Ore',
        'Nether Brick Stairs',
        'Netherrack',
        'Oak Wood Slab',
        'Oak Wood Stairs',
        'Obsidian',
        'Packed Ice',
        'Podzol',
        'Polished Andesite',
        'Polished Diorite',
        'Polished Granite',
        'Quartz Slab',
        'Quartz Slab (Upper)',
        'Quartz Stairs',
        'Red Sand',
        'Redstone Ore',
        'Redstone Ore (Glowing)',
        'Sand',
        'Sandstone',
        'Sandstone Slab',
        'Sandstone Slab (Upper)',
        'Sandstone Stairs',
        'Smooth Double Stone Slab',
        'Smooth Double Sandstone Slab',
        'Snow',
        'Soul Sand',
        'Spruce Wood Slab',
        'Spruce Wood Stairs',
        'Stained Clay',
        'Stone',
        'Stone Brick Slab',
        'Stone Brick Slab (Upper)',
        'Stone Brick Stairs',
        'Stone Bricks',
        'Stone Slab',
        'Stone Slab (Upper)',
        'Wood Planks',
        'Wooden Slab (Old)',
        'Wooden Slab (Old) (Upper)',
        
        # Indev/classic
        'Infinite lava source',
        
        # Pocket
        'Glowing Obsidian',
        'Update Game Block',
    )
    
    # These will be retained in place if there is terrain beneath to support them    
    supported = (
        # Alpha blocks
        '(Unused Shrub)',
        'Acacia Sapling',
        'Activator Rail',
        'Anvil',
        'Bed',
        'Beacon Block',
        'Birch Sapling',
        'Bookshelf',
        'Brewing Stand',
        'Brown Mushroom',
        'Cauldron',
        'Cake',
        'Carpet',
        'Carrots',
        'Chest',
        'Cobblestone Wall',
        'Command Block',
        'Cobweb',
        'Crafting Table',
        'Dark Oak Sapling',
        'Daylight Sensor',
        'Dead Shrub',
        'Detector Rail',
        'Dispenser',
        'Dragon Egg',
        'Dropper',
        'Enchantment Table',
        'End Portal',
        'Ender Chest',
        'Farmland',
        'Fence',
        'Fence Gate',
        'Fern',
        'Flower',
        'Flower Pot',
        'Furnace',
        'Glass',
        'Glass Pane',
        'Hopper',
        'Iron Bars',
        'Iron Door',
        "Jack-o'-Lantern",
        'Jukebox',
        'Jungle Sapling',
        'Large Flowers',
        'Lily Pad',
        'Lit Furnace',
        'Melon Stem',
        'Mob Head',
        'Monster Spawner',
        'Mossy Cobblestone Wall',
        'Nether Brick Fence',
        'Nether Wart',
        'Note Block',
        'Oak Sapling',
        'Potatoes',
        'Powered Rail',
        'Pumpkin',
        'Pumpkin Stem',
        'Rail',
        'Red Mushroom',
        'Redstone Comparator (Off)',
        'Redstone Comparator (On)',
        'Redstone Lamp (Off)',
        'Redstone Lamp (On)',
        'Redstone Repeater (Off)',
        'Redstone Repeater (On)',
        'Redstone Wire',
        'Poppy',
        'Sign Post',
        'Snow Layer',
        'Sponge',
        'Spruce Sapling',
        'Stained Glass',
        'Stained Glass Pane',
        'Stone Pressure Plate',
        'TNT',
        'TNT (Primed)',
        'Tall Grass',
        'Trapdoor',
        'Trapped Chest',
        'Watermelon',
        'Weighted Pressure Plate (Light)',
        'Weighted Pressure Plate (Heavy)',
        'Wheat',
        'Wooden Door',
        'Wooden Pressure Plate',
        
        # Pocket
        'Nether Reactor Core',
        'Stonecutter',
    )
    
    # These will be retained in place if there is a supported block beneath them on top of terrain
    supported2 = (
        'Large Flowers',
    )
    
    # These will never be removed
    immutable = (
        # Alpha blocks
        'Bedrock',
        
        # Pocket
        'Invisible Bedrock',
    )
    
    # These blocks are able to disolve other blocks
    solvent = (
        # Alpha
        'Water',
        'Water (Flowing)',
        
        # Indev/classic
        'Infinite water source',
    )
    
    # These blocks will be replaced as specified if underwater (None means completely remove)
    disolve = {
        # Alpha blocks
        'Grass': 'Dirt',
        'Lava': 'Obsidian',
        'Lava (Flowing)': 'Cobblestone',
        'Mycelium': 'Dirt',
        'Podzol': 'Dirt',
        'Snow': 'Dirt',
        'Snow Layer': None,
        
        # Indev/classic
        'Infinite lava source': 'Obsidian',
    }
    
    # Ignored when reshaping land
    water = (
        # Alpha
        'Ice',
        'Water',
        'Water (Flowing)',
        
        # Indev/classic
        'Infinite water source',
    )
    
    # Tree trunks
    tree_trunks = (
        'Acacia Wood (East/West)',
        'Acacia Wood (North/South)',
        'Acacia Wood (Upright)',
        'Birch Wood (East/West)',
        'Birch Wood (North/South)',
        'Birch Wood (Upright)',
        'Cactus',
        'Dark Oak Wood (East/West)',
        'Dark Oak Wood (North/South)',
        'Dark Oak Wood (Upright)',
        'Jungle Wood (East/West)',
        'Jungle Wood (North/South)',
        'Jungle Wood (Upright)',
        'Oak Wood (East/West)',
        'Oak Wood (North/South)',
        'Oak Wood (Upright)',
        'Spruce Wood (East/West)',
        'Spruce Wood (North/South)',
        'Spruce Wood (Upright)',
        'Sugar Cane',
    )
    
    # Leaves and their decayed versions
    tree_leaves = (
        'Acacia Leaves',
        'Acacia Leaves (Decaying)',
        'Acacia Leaves (Permanent)',
        'Birch Leaves',
        'Birch Leaves (Decaying)',
        'Birch Leaves (No Decay)',
        'Dark Oak Leaves',
        'Dark Oak Leaves (Decaying)',
        'Dark Oak Leaves (Permanent)',
        'Jungle Leaves',
        'Jungle Leaves (Decaying)',
        'Jungle Leaves (No Decay)',
        'Oak Leaves',
        'Oak Leaves (Decaying)',
        'Oak Leaves (Permanent)',
        'Spruce Leaves',
        'Spruce Leaves (Decaying)',
        'Spruce Leaves (No Decay)',
    )
    
    # Tree trunk replace
    tree_trunks_replace = {
        'Acacia Wood (East/West)'       : 'Acacia Sapling',
        'Acacia Wood (North/South)'     : 'Acacia Sapling',
        'Acacia Wood (Upright)'         : 'Acacia Sapling',
        'Birch Wood (East/West)'        : 'Birch Sapling',
        'Birch Wood (North/South)'      : 'Birch Sapling',
        'Birch Wood (Upright)'          : 'Birch Sapling',
        'Dark Oak Wood (East/West)'     : 'Dark Oak Sapling',
        'Dark Oak Wood (North/South)'   : 'Dark Oak Sapling',
        'Dark Oak Wood (Upright)'       : 'Dark Oak Sapling',
        'Jungle Wood (East/West)'       : 'Jungle Sapling',
        'Jungle Wood (North/South)'     : 'Jungle Sapling',
        'Jungle Wood (Upright)'         : 'Jungle Sapling',
        'Oak Wood (East/West)'          : 'Oak Sapling',
        'Oak Wood (North/South)'        : 'Oak Sapling',
        'Oak Wood (Upright)'            : 'Oak Sapling',
        'Spruce Wood (East/West)'       : 'Spruce Sapling',
        'Spruce Wood (North/South)'     : 'Spruce Sapling',
        'Spruce Wood (Upright)'         : 'Spruce Sapling',
        'Sugar Cane'                    : 'Sugar Cane',
    }
    
    # Blocks that should also be updated by the game
    update = tree_leaves + (
        'Vines',
    )

    BlockRoleIDs = collections.namedtuple('BlockIDs', [
        'terrain', 'supported', 'supported2', 'immutable', 'solvent',
        'disolve', 'water', 'tree_trunks', 'tree_leaves',
        'tree_trunks_replace', 'update',
    ])
    
    processing_order = ('even', 'river', 'tidy')
    
    def __init__(self, world_dir):
        self.__level = mclevel.fromFile(world_dir)
        self.__block_roles = self.BlockRoleIDs(
            self.__block_material(self.terrain),
            self.__block_material(self.supported),
            self.__block_material(self.supported2),
            self.__block_material(self.immutable),
            self.__block_material(self.solvent),
            self.__block_material(self.disolve, ('ID', ('ID', 'blockData'))),
            self.__block_material(self.water),
            self.__block_material(self.tree_trunks),
            self.__block_material(self.tree_leaves),
            self.__block_material(self.tree_trunks_replace, (('ID', 'blockData'), None)),
            self.__block_material(self.update),
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
            
        def hasname_or_none(obj, name):
            return True if name is None else name in obj
        
        def getname_or_none(obj, name):
            return None if name is None else obj[name]
        
        materials = {}
        for block in self.__level.materials:
            materials[block.name] = block
            for alt in (x.strip() for x in block.aka.split(',')):
                if alt not in materials:
                    materials[alt] = block
        
        # TODO: Add an option to dump all unmatched names... and all materials not covered by names
        
        if names is not None and hasattr(names, 'iteritems'):
            attr_funs = [getter(attr) for attr in itertools.islice(cycle(attrs), 2)]
            return dict([attr_funs[i](getname_or_none(materials, n)) for i, n in enumerate(ns)]
                        for ns in names.iteritems()
                        if all(hasname_or_none(materials, n) for n in ns))
        else:
            atr = getter(attrs)
            return set(atr(getname_or_none(materials, n)) for n in names if hasname_or_none(materials, n))
    
    def __give_surrounding(self, coords, radius):
        """ List all surrounding chunks including the centre """
        
        range = (-radius, radius+1)
        for z in xrange(*range):
            for x in xrange(*range):
                yield (coords[0] + x, coords[1] + z)
        
    def __have_surrounding(self, coords, radius):
        """ Check if all surrounding chunks are present """
        
        for chunk in self.__give_surrounding(coords, radius):
            if chunk not in self.__level.allChunks:
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
            processed = set()
            for coord in (k for k, v in contour.edges.iteritems() if v.method & method_bit != 0):
                # Progress logging
                if self.log_function is not None:
                    if n % self.log_interval == 0:
                        self.log_function(n)

                # Check if we have to deal with surrounding chunks
                if ChunkShaper.filt_is_even(method):
                    radius = self.filt_radius_even
                    padding = self.filt_padding_even
                else:
                    radius = self.filt_radius_river
                    padding = self.filt_padding_river
                    
                # We only re-shape when surrounding chunks are present to prevent river spillage
                # and ensure padding requirements can be fulfilled
                if self.__have_surrounding(coord, radius + padding):
                    def reshape(chunk):
                        # Don't re-process anything
                        if chunk in processed:
                            return
                        
                        # Process central chunk
                        if chunk == coord:
                            edge = contour.edges[chunk]
                        
                        # Process chunks on the periphery only so that main edge chunks are reshaped right in the centre of the padded area
                        # TODO: When processing peripheral chunks, they should really be processed along with the central coordinate
                        #       that is closest to one of the edge contour chunks.
                        else:
                            if chunk in contour.edges:
                                return
                            else:
                                edge = EdgeData(contour.edges[coord].method, set())
                            
                        # Do the processing
                        cs = ChunkShaper(self.__level.getChunk(*chunk), edge, padding, height_map, self.__block_roles)
                        cs.reshape(method)
                        processed.add(chunk)
                        height_map.invalidations.add(chunk)
                    
                    for chunk in self.__give_surrounding(coord, radius):
                        reshape(chunk)
                        
                    reshaped[method].append(coord)
                
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

