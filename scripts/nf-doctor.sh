#!/usr/bin/env bash




#   wsl -d Ubuntu-24.04 bash -s < scripts/nf-doctor.sh
set -uo pipefail

PREFIX="${NF_QEMU_PREFIX:-/opt/qemu-nf}"
export PATH="${PREFIX}/bin:${PATH}"
FAIL=0
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

ok()   { printf "  [ OK ] %-34s %s\n" "$1" "${2:-}"; }
bad()  { printf "  [FAIL] %-34s %s\n" "$1" "${2:-}"; FAIL=1; }
warn() { printf "  [WARN] %-34s %s\n" "$1" "${2:-}"; }

echo "=== NodeFusion 环境体检 ==="
echo
echo "1. 基础系统"
. /etc/os-release 2>/dev/null || true
ok "发行版" "${PRETTY_NAME:-unknown}"
ok "内核" "$(uname -r)"
ok "CPU 线程" "$(nproc)"

echo
echo "2. 交叉工具链（编译 xv6）"
for tool in riscv64-unknown-elf-gcc riscv64-unknown-elf-ld \
            riscv64-unknown-elf-objdump riscv64-unknown-elf-objcopy \
            make gcc bc; do
    if command -v "$tool" >/dev/null 2>&1; then
        ok "$tool" "$("$tool" --version 2>/dev/null | head -1 | cut -c1-60)"
    else
        bad "$tool" "未安装"
    fi
done

echo
echo "3. QEMU"
if command -v qemu-system-riscv64 >/dev/null 2>&1; then
    QV="$(qemu-system-riscv64 --version | head -1)"
    QPATH="$(command -v qemu-system-riscv64)"
    ok "qemu-system-riscv64" "${QV}"
    if [ "${QPATH}" = "${PREFIX}/bin/qemu-system-riscv64" ]; then
        ok "使用自建 QEMU" "${QPATH}"
    else
        warn "使用发行版 QEMU" "${QPATH}（plugin API 较旧，功能受限）"
    fi
else
    bad "qemu-system-riscv64" "未安装"
fi

if [ -f "${PREFIX}/include/qemu-plugin.h" ]; then
    APIV="$(sed -n 's/^#define QEMU_PLUGIN_VERSION *//p' "${PREFIX}/include/qemu-plugin.h" | head -1)"
    ok "qemu-plugin.h" "plugin API v${APIV}"
    for sym in qemu_plugin_read_register qemu_plugin_read_memory_vaddr \
               qemu_plugin_register_vcpu_mem_cb qemu_plugin_register_vcpu_tb_trans_cb; do
        if grep -q "$sym" "${PREFIX}/include/qemu-plugin.h"; then
            ok "  API: $sym" ""
        else
            bad "  API: $sym" "该 QEMU 版本不提供，外部观测能力会退化"
        fi
    done
else
    bad "qemu-plugin.h" "缺失，无法编译 NodeFusion plugin"
fi

echo
echo "4. TCG plugin 编译与加载（端到端冒烟）"
cat > "${TMP}/smoke.c" <<'CEOF'
#include <stdio.h>
#include <stdint.h>
#include <qemu-plugin.h>
QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;
static uint64_t insns;
static const char *outpath;
static void tb_exec(unsigned int c, void *u) { insns += (uint64_t)(uintptr_t)u; }
static void tb_trans(qemu_plugin_id_t id, struct qemu_plugin_tb *tb) {
    qemu_plugin_register_vcpu_tb_exec_cb(tb, tb_exec, QEMU_PLUGIN_CB_NO_REGS,
                                         (void *)(uintptr_t)qemu_plugin_tb_n_insns(tb));
}
static void at_exit(qemu_plugin_id_t id, void *p) {
    FILE *f = fopen(outpath, "w");
    if (!f) return;
    fprintf(f, "%llu\n", (unsigned long long)insns);
    fclose(f);
}
QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id, const qemu_info_t *info,
                                           int argc, char **argv) {
    outpath = (argc > 0) ? strchr(argv[0], '=') + 1 : "/tmp/nf-smoke.out";
    qemu_plugin_register_vcpu_tb_trans_cb(id, tb_trans);
    qemu_plugin_register_atexit_cb(id, at_exit, NULL);
    return 0;
}
CEOF
if gcc -O2 -fPIC -shared -o "${TMP}/libsmoke.so" "${TMP}/smoke.c" \
        -I"${PREFIX}/include" $(pkg-config --cflags glib-2.0 2>/dev/null) 2>"${TMP}/cc.log"; then
    ok "plugin 编译" "libsmoke.so"
else
    bad "plugin 编译" "$(head -2 "${TMP}/cc.log" | tr '\n' ' ')"
fi





if [ -f "${TMP}/libsmoke.so" ]; then
    timeout 10 qemu-system-riscv64 -machine virt -m 128M -nographic \
        -plugin "${TMP}/libsmoke.so,out=${TMP}/smoke.out" \
        </dev/null >"${TMP}/qemu.log" 2>&1
    if [ -f "${TMP}/smoke.out" ] && [ "$(cat "${TMP}/smoke.out")" != "0" ]; then
        ok "plugin 加载与计数" "$(cat "${TMP}/smoke.out") 条指令"
    else
        bad "plugin 加载与计数" "无输出，见 ${TMP}/qemu.log"
    fi
fi

echo
echo "5. 与 Windows 侧的协作"


if command -v python.exe >/dev/null 2>&1; then
    ok "Windows Python 互操作" "$(python.exe -V </dev/null 2>&1 | tr -d '\r')"
else
    bad "Windows Python 互操作" "WSL 里调不到 python.exe（检查 WSL interop 与 Windows PATH）"
fi
if [ -d /mnt/e ]; then
    ok "Windows 盘符挂载" "/mnt/e 可见"
else
    warn "Windows 盘符挂载" "/mnt/e 不存在，请确认仓库所在盘符"
fi

echo
if [ "${FAIL}" -eq 0 ]; then
    echo "=== 全部通过 ==="
else
    echo "=== 存在失败项，请按上面的 [FAIL] 处理后重跑 ==="
fi
exit "${FAIL}"
