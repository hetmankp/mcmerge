import itertools
import numpy
from pymclevel import mclevel

class Shifter(object):
    """
    Shifts areas of the map up or down.
    """
    
    relight = True
    
    def __init__(self, world_dir):
        self.__level = mclevel.fromFile(world_dir)
        
        self.log_interval = 1
        self.log_function = None
        
        self.__measured = (None, None)
    
    @property
    def level(self):
        return self.__level
    
    def mark(self, contour, distance):
        for coord in self.__level.allChunks:
            contour.shift[coord] = distance
        
    def shift_all(self, distance):
        return self.__shift(itertools.izip(self.__level.allChunks, itertools.repeat(distance)))
    
    def shift_marked(self, contour):
        return self.__shift(contour.shift.iteritems())
    
    def __measure(self, height, distance):
        # Return memoised value
        args = (height, distance)
        if args == self.__measured[0]:
            return self.__measured[1]
            
        # Calculate shift coordinates
        if distance == 0:
            yfrom = (0, height)
            yto = (0, height)
            ybuffer = (0, 0)
        elif distance < 0:
            yfrom = (1 - distance, height)
            yto = (1, height + distance)
            ybuffer = (height + distance, height)
        elif distance > 0:
            yfrom = (1, height - distance)
            yto = (1 + distance, height)
            ybuffer = (1, 1 + distance)
            
        self.__measured = (args, (yfrom, yto, ybuffer))
        
        return self.__measured[1]
        
    def __shift(self, distances):
        # Prelims
        height = self.__level.Height
            
        # Go through all the chunks and data provided
        n = 0
        for n, (coord, distance) in enumerate(distances):
            # Get measured boundaries
            if distance == 0:
                continue
            else:
                yfrom, yto, ybuffer = self.__measure(height, distance)
            
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
        n = 0
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

