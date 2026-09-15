# NodeFusion TCG Plugin 构建
#
# 需要带 --enable-plugins 的 QEMU。
#   Linux / WSL：本项目用 /opt/qemu-nf 下自建的版本，见 scripts/nf-setup-wsl.sh
#   macOS      ：Homebrew 的 qemu 默认就带 plugin 支持，前缀为 /opt/homebrew
# 环境搭建见仓库根目录 NodeFusion_环境准备说明.md。

UNAME_S := $(shell uname -s)

ifeq ($(UNAME_S),Darwin)
  # macOS：
  #   1) 产物是 .dylib（dlopen 不看扩展名，但按平台惯例命名）
  #   2) qemu_plugin_* 符号在链接期不存在，由 QEMU 在 dlopen 时提供。Mach-O 默认
  #      两级命名空间会在链接期就报 undefined symbol，必须显式放行延迟绑定。
  #   3) 不显式链 glib：QEMU 进程里已有一份，插件按同样方式延迟绑定过去，
  #      避免在同一进程里引入第二份 glib 实例。
  NF_QEMU_PREFIX ?= /opt/homebrew
  TARGET         := libnf.dylib
  LDFLAGS        := -shared -Wl,-undefined,dynamic_lookup
  SETUP_HINT     := brew install qemu glib pkg-config
else
  NF_QEMU_PREFIX ?= /opt/qemu-nf
  TARGET         := libnf.so
  LDFLAGS        := -shared
  SETUP_HINT     := scripts/nf-setup-wsl.sh
endif

PLUGIN_INC  := $(NF_QEMU_PREFIX)/include
GLIB_CFLAGS := $(shell pkg-config --cflags glib-2.0)

CFLAGS  := -O2 -g -fPIC -Wall -Wextra -Wno-unused-parameter -std=gnu11
CFLAGS  += -I$(PLUGIN_INC) $(GLIB_CFLAGS)
LDLIBS  := -lz

all: $(TARGET)

$(TARGET): nf_plugin.c
	@if [ ! -f "$(PLUGIN_INC)/qemu-plugin.h" ]; then \
		echo "错误：找不到 $(PLUGIN_INC)/qemu-plugin.h"; \
		echo "      当前平台：$(UNAME_S)，前缀：$(NF_QEMU_PREFIX)"; \
		echo "      请先执行：$(SETUP_HINT)"; \
		echo "      或用 NF_QEMU_PREFIX=<前缀> make 指定其他 QEMU 安装位置"; \
		exit 1; \
	fi
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LDLIBS)
	@echo "构建完成：$(CURDIR)/$@"

clean:
	rm -f libnf.so libnf.dylib

.PHONY: all clean
