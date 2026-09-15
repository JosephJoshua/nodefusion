#!/usr/bin/env bash




#   wsl -d Ubuntu-24.04 -u root bash -s < scripts/nf-setup-wsl.sh
set -euo pipefail

QEMU_VERSION="${NF_QEMU_VERSION:-11.0.3}"
PREFIX="${NF_QEMU_PREFIX:-/opt/qemu-nf}"
BUILD_DIR="${NF_BUILD_DIR:-/opt/nf-build}"

if [ "$(id -u)" -ne 0 ]; then
    echo "错误：请以 root 运行（wsl -u root）" >&2
    exit 1
fi

echo "==> [1/4] 安装 apt 依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
    build-essential git bc \
    gcc-riscv64-unknown-elf binutils-riscv64-unknown-elf \
    gdb-multiarch qemu-system-misc \
    ninja-build pkg-config libglib2.0-dev libpixman-1-dev zlib1g-dev \
    flex bison python3-venv ca-certificates curl xz-utils









echo "==> [2/4] 编译带 --enable-plugins 的 QEMU ${QEMU_VERSION}"
if [ -x "${PREFIX}/bin/qemu-system-riscv64" ] && \
   "${PREFIX}/bin/qemu-system-riscv64" --version | grep -q "${QEMU_VERSION}"; then
    echo "    已存在 ${PREFIX}，跳过编译"
else
    mkdir -p "${BUILD_DIR}"
    cd "${BUILD_DIR}"
    [ -f "qemu-${QEMU_VERSION}.tar.xz" ] || \
        curl -fSL -o "qemu-${QEMU_VERSION}.tar.xz" \
            "https://download.qemu.org/qemu-${QEMU_VERSION}.tar.xz"
    rm -rf "qemu-${QEMU_VERSION}"
    tar xf "qemu-${QEMU_VERSION}.tar.xz"
    mkdir -p "qemu-${QEMU_VERSION}/build"
    cd "qemu-${QEMU_VERSION}/build"
    ../configure --prefix="${PREFIX}" \
        --target-list=riscv64-softmmu \
        --enable-plugins --disable-werror \
        --disable-docs --disable-sdl --disable-gtk --disable-vnc \
        --disable-spice --disable-tools --disable-guest-agent
    ninja -j"$(nproc)"
    ninja install
fi

echo "==> [3/4] 安装 plugin 头文件"


mkdir -p "${PREFIX}/include"
SRC_HDR="${BUILD_DIR}/qemu-${QEMU_VERSION}/include/plugins/qemu-plugin.h"
if [ -f "${SRC_HDR}" ]; then
    cp "${SRC_HDR}" "${PREFIX}/include/"
elif [ ! -f "${PREFIX}/include/qemu-plugin.h" ]; then
    echo "错误：找不到 qemu-plugin.h，NodeFusion plugin 将无法编译" >&2
    exit 1
fi

echo "==> [4/4] 写入 PATH 配置"
cat > /etc/profile.d/nodefusion.sh <<'PEOF'

export NF_QEMU_PREFIX=/opt/qemu-nf
export PATH=/opt/qemu-nf/bin:$PATH
PEOF
chmod 644 /etc/profile.d/nodefusion.sh

echo
echo "==> 完成。请运行 scripts/nf-doctor.sh 做验证。"
"${PREFIX}/bin/qemu-system-riscv64" --version | head -1
