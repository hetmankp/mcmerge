TAG ?= $(shell date '+%Y%m%d_%H%M')
WIN32_PKG = mcmerge-win32-$(TAG).zip
SCRPT_PKG = mcmerge-script-$(TAG).zip
BUILD_DIR = build
DIST_DIR = dist
SCRPT_BUILD = $(BUILD_DIR)/assemble

all: $(DIST_DIR)/$(SCRPT_PKG) $(DIST_DIR)/$(WIN32_PKG)

clean:
	-rm -r $(BUILD_DIR)
	-rm -r $(DIST_DIR)

FORCE:

$(DIST_DIR)/mcmerge.exe: FORCE
	python setup.py py2exe

$(DIST_DIR)/LICENCE.txt: LICENCE.txt pymclevel/LICENSE.txt
	mkdir -p $(DIST_DIR)
	echo "mcmerge licence" | unix2dos > $@
	echo "---------------" | unix2dos >> $@
	cat LICENCE.txt | unix2dos >> $@
	echo | unix2dos >> $@
	echo | unix2dos >> $@
	echo "pymclevel licence" | unix2dos >> $@
	echo "-----------------" | unix2dos >> $@
	cat pymclevel/LICENSE.txt | unix2dos >> $@

$(DIST_DIR)/$(WIN32_PKG): $(DIST_DIR)/mcmerge.exe $(DIST_DIR)/LICENCE.txt
	mkdir -p $(DIST_DIR)
	cat README.md | sed 's/\\\\/\\/g' > $(DIST_DIR)/README.txt
	(cd $(DIST_DIR); zip -m $(WIN32_PKG) mcmerge.exe mcmerge.lib README.txt LICENCE.txt)

$(DIST_DIR)/$(SCRPT_PKG): FORCE
	mkdir -p $(DIST_DIR)
	-rm -r $(SCRPT_BUILD)
	mkdir -p $(SCRPT_BUILD)
	mkdir -p $(SCRPT_BUILD)/pymclevel
	cat README.md | sed 's/\\\\/\\/g' > $(SCRPT_BUILD)/README.txt
	cp LICENCE.txt *.py $(SCRPT_BUILD)
	cp $(addprefix pymclevel/,LICENSE.txt README.txt items.txt *.py) $(SCRPT_BUILD)/pymclevel
	(cd $(SCRPT_BUILD); zip -r $(SCRPT_PKG) *)
	mv $(SCRPT_BUILD)/$(SCRPT_PKG) $(DIST_DIR)/$(SCRPT_PKG)
