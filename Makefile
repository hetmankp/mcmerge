TAG := $(shell date '+%Y%m%d_%H%M')
WIN32_PKG = mcmerge-win32-$(TAG).zip
SCRPT_PKG = mcmerge-script-$(TAG).zip
BUILD_DIR = build
DIST_DIR = dist
WINEXE_BUILD = $(BUILD_DIR)/winexe
SCRIPT_BUILD = $(BUILD_DIR)/script

ifeq ($(OS),Windows_NT)
all: all-script all-win32
else
all: all-script
endif

all-script: $(DIST_DIR)/$(SCRPT_PKG)

all-win32: $(DIST_DIR)/$(WIN32_PKG)

FIXLINE=unix2dos

define MD2TXT
    sed -e 's/\\\\/\\/g' -e 's/&lt;/</g' -e 's/&gt;/>/g' \
    	| sed -e '/^    /!s/<\/\?code>//g' \
	| perl -pe 's/__(.*?)__/\1/g' \
	| $(FIXLINE)
endef

clean:
	-rm -r $(BUILD_DIR)
	-rm -r $(DIST_DIR)

FORCE:

$(WINEXE_BUILD)/mcmerge.exe: FORCE
	python setup.py py2exe

$(WINEXE_BUILD)/LICENCE.txt: LICENCE.txt pymclevel/LICENSE.txt
	mkdir -p $(WINEXE_BUILD)
	echo "mcmerge licence" | $(FIXLINE) > $@
	echo "---------------" | $(FIXLINE) >> $@
	cat LICENCE.txt | $(FIXLINE) >> $@
	echo | $(FIXLINE) >> $@
	echo | $(FIXLINE) >> $@
	echo "pymclevel licence" | $(FIXLINE) >> $@
	echo "-----------------" | $(FIXLINE) >> $@
	cat pymclevel/LICENSE.txt | $(FIXLINE) >> $@

$(WINEXE_BUILD)/$(WIN32_PKG): $(WINEXE_BUILD)/mcmerge.exe $(WINEXE_BUILD)/LICENCE.txt
	mkdir -p $(WINEXE_BUILD)
	cat README.md | $(MD2TXT) > $(WINEXE_BUILD)/README.txt
	cat CONTOUR.md | $(MD2TXT) > $(WINEXE_BUILD)/CONTOUR.txt
	python package_files "$(WINEXE_BUILD)/mcmerge.lib" 'pymclevel/*.yaml' 'pymclevel/*.txt' 'pymclevel/_nbt.*'
	(cd $(WINEXE_BUILD); zip -r $(WIN32_PKG) *)

$(DIST_DIR)/$(WIN32_PKG): $(WINEXE_BUILD)/$(WIN32_PKG)
	mkdir -p $(DIST_DIR)
	mv $(WINEXE_BUILD)/$(WIN32_PKG) $(DIST_DIR)/$(WIN32_PKG)

$(SCRIPT_BUILD)/$(SCRPT_PKG): FORCE
	mkdir -p $(DIST_DIR)
	-rm -r $(SCRIPT_BUILD)
	mkdir -p $(SCRIPT_BUILD)
	cat README.md | $(MD2TXT) > $(SCRIPT_BUILD)/README.txt
	cat CONTOUR.md | $(MD2TXT) > $(SCRIPT_BUILD)/CONTOUR.txt
	cat LICENCE.txt | $(FIXLINE) > $(SCRIPT_BUILD)/LICENCE.txt
	cp *.py $(SCRIPT_BUILD)
	find pymclevel -name '*.pyc' -o -name .gitignore \
	            -o \( -path */.git -o -path pymclevel/testfiles \
	            -o -path pymclevel/regression_test \) -prune -o -print \
	    | while read file; do if [ -d "$$file" ]; then mkdir -p "$(SCRIPT_BUILD)/$$file"; else cp "$$file" "$(SCRIPT_BUILD)/$$file"; fi; done
	cp $(addprefix pymclevel/,*.py *.yaml _nbt.* *.txt) $(SCRIPT_BUILD)/pymclevel
	(cd $(SCRIPT_BUILD); zip -r $(SCRPT_PKG) *)

$(DIST_DIR)/$(SCRPT_PKG): $(SCRIPT_BUILD)/$(SCRPT_PKG)
	mkdir -p $(DIST_DIR)
	mv $(SCRIPT_BUILD)/$(SCRPT_PKG) $(DIST_DIR)/$(SCRPT_PKG)
