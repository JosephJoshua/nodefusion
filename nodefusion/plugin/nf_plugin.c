

































#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <glib.h>
#include <zlib.h>
#include <qemu-plugin.h>

QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;








#define NF_MAGIC        "NFTRACE\x01"



#define NF_FORMAT_VER   2u

enum nf_rec_type {
    NF_REC_META     = 1,
    NF_REC_SAMPLE   = 2,
    NF_REC_DISCON   = 3,
    NF_REC_WATCHPC  = 4,
    NF_REC_SNAPMARK = 5,
    NF_REC_RAMPAGE  = 6,
    NF_REC_IDLE     = 7,
    NF_REC_VCPU     = 8,
    NF_REC_WARN     = 9,
    NF_REC_END      = 10,
    NF_REC_NFTRACE  = 11,
};


struct nf_rec_hdr {
    uint8_t  type;
    uint8_t  cpu;
    uint16_t len;
    uint32_t flags;
    uint64_t insn;
} __attribute__((packed));


#define NF_F_NO_REGS    (1u << 0)
#define NF_F_NO_CSR     (1u << 1)
#define NF_F_TRUNCATED  (1u << 2)
#define NF_F_ZLIB       (1u << 3)
#define NF_F_INCOMPLETE (1u << 4)
#define NF_F_NO_MCSR    (1u << 5)


struct nf_pl_sample {
    uint64_t pc;
    uint64_t satp;
    uint64_t sstatus;
    uint32_t priv;
    uint32_t _pad;
} __attribute__((packed));
















struct nf_pl_discon {
    uint32_t discon_type;   /* enum qemu_plugin_discon_type */
    uint32_t priv;
    uint64_t from_pc;
    uint64_t to_pc;
    uint64_t scause;
    uint64_t sepc;
    uint64_t stval;
    uint64_t satp;
    uint64_t sstatus;
    uint64_t a[8];

    uint64_t sp;

    uint64_t mcause;
    uint64_t mepc;
    uint64_t mtval;
} __attribute__((packed));


struct nf_pl_watchpc {
    uint32_t watch_id;
    uint32_t priv;
    uint64_t pc;
    uint64_t satp;
    uint64_t a[8];
    uint64_t sp;
    uint64_t ra;
} __attribute__((packed));


struct nf_pl_snapmark {
    uint64_t snap_seq;
    uint64_t ram_base;
    uint32_t page_size;
    uint32_t pages_changed;
    uint32_t pages_total;
    uint32_t _pad;
} __attribute__((packed));







struct nf_pl_rampage {
    uint32_t page_index;
    uint32_t raw_len;

} __attribute__((packed));


struct nf_pl_end {
    uint64_t total_insns;
    uint64_t snapshots;
    uint64_t discons;
    uint64_t samples;
    uint64_t watch_hits;
    uint64_t ram_bytes;
    uint32_t truncated;
    uint32_t _pad;





    uint64_t watch_drops;
} __attribute__((packed));





#define NF_MAX_VCPUS 16


struct nf_regs {
    struct qemu_plugin_register *pc;
    struct qemu_plugin_register *priv;
    struct qemu_plugin_register *satp;
    struct qemu_plugin_register *scause;
    struct qemu_plugin_register *sepc;
    struct qemu_plugin_register *stval;
    struct qemu_plugin_register *sstatus;
    struct qemu_plugin_register *mcause;
    struct qemu_plugin_register *mepc;
    struct qemu_plugin_register *mtval;
    struct qemu_plugin_register *sp;
    struct qemu_plugin_register *ra;
    struct qemu_plugin_register *a[8];
    bool ready;
};

struct nf_watch {
    uint64_t addr;
    char    *name;
    bool     snap;






    bool     throttle;




    bool     nftrace;











    uint32_t rate;
    uint64_t hits;
};


struct nf_nftrace_rec {
    uint64_t type;
    uint64_t a[4];
};

static struct {
    FILE     *out;
    GMutex    lock;


    qemu_plugin_u64 insn_count;
    struct qemu_plugin_scoreboard *sb;











    uint64_t  sample_every;
    uint64_t  snap_every;
    uint64_t  boot_snap_every;
    uint64_t  snap_start;
    bool      start_snap_done;
    uint64_t  next_sample;
    uint64_t  next_snap;


    uint64_t  ram_base;
    uint64_t  ram_size;
    uint32_t  page_size;
    uint32_t  page_count;
    uint8_t **shadow_pages;
    bool     *shadow_valid;
    uint8_t  *zbuf;
    uLongf    zbuf_cap;
    GByteArray *writebuf;


    uint64_t  max_ram_bytes;
    uint64_t  ram_bytes;
    bool      truncated;
    uint64_t  snapshot_reads;
    uint64_t  snapshot_fallbacks;
    uint64_t  snapshot_us;
    unsigned  ncpus;











    uint64_t  max_insn;


    GHashTable *watch_by_addr;   /* addr -> (id+1) */
    struct nf_watch *watches;
    unsigned  n_watches;


    uint64_t  ev_snap_min;
    uint64_t  ev_snap_max;
    uint64_t  n_ev_snaps;
    uint64_t  last_ev_snap_insn;

    uint64_t  n_nftrace;
    uint64_t  n_nftrace_fail;

    struct nf_regs regs[NF_MAX_VCPUS];


    uint64_t  n_samples, n_discons, n_watch_hits, n_snapshots;


    uint64_t  n_watch_drops;

    bool      started;
    bool      final_snap_done;
} nf;





static void nf_die(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "[nodefusion-plugin] 致命错误：");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);

    exit(2);
}

static void nf_write_rec(uint8_t type, uint8_t cpu, uint32_t flags,
                         uint64_t insn, const void *payload, uint16_t len,
                         const void *extra, size_t extra_len)
{






    if (!nf.out) return;

    struct nf_rec_hdr h = {
        .type = type, .cpu = cpu, .len = (uint16_t)(len + extra_len),
        .flags = flags, .insn = insn,
    };
    g_byte_array_set_size(nf.writebuf, 0);
    g_byte_array_append(nf.writebuf, (const uint8_t *)&h, sizeof(h));
    if (len) g_byte_array_append(nf.writebuf, payload, len);
    if (extra_len) g_byte_array_append(nf.writebuf, extra, extra_len);
    if (fwrite(nf.writebuf->data, nf.writebuf->len, 1, nf.out) != 1)
        nf_die("写轨迹失败：%s", strerror(errno));
}

static void nf_meta(const char *fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n < 0) return;
    nf_write_rec(NF_REC_META, 0, 0, 0, buf, (uint16_t)MIN((size_t)n, sizeof(buf)), NULL, 0);
}

static void nf_warn(uint64_t insn, const char *fmt, ...)
{
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n < 0) return;
    fprintf(stderr, "[nodefusion-plugin] 告警：%s\n", buf);
    nf_write_rec(NF_REC_WARN, 0, 0, insn, buf, (uint16_t)MIN((size_t)n, sizeof(buf)), NULL, 0);
}







static GByteArray *nf_regbuf[NF_MAX_VCPUS];

static GByteArray *nf_vcpu_buf(unsigned int vcpu)
{
    unsigned int slot = vcpu < NF_MAX_VCPUS ? vcpu : 0;
    return nf_regbuf[slot];
}

static bool nf_read_reg(unsigned int vcpu, struct qemu_plugin_register *h,
                        uint64_t *out)
{
    if (!h) return false;
    GByteArray *buf = nf_vcpu_buf(vcpu);
    g_byte_array_set_size(buf, 0);
    if (!qemu_plugin_read_register(h, buf)) return false;
    uint64_t v = 0;
    size_t n = MIN(buf->len, sizeof(v));
    memcpy(&v, buf->data, n);
    *out = v;
    return true;
}

static struct qemu_plugin_register *nf_find_reg(GArray *regs, const char *name)
{
    for (guint i = 0; i < regs->len; i++) {
        qemu_plugin_reg_descriptor *d =
            &g_array_index(regs, qemu_plugin_reg_descriptor, i);
        if (g_strcmp0(d->name, name) == 0) return d->handle;
    }
    return NULL;
}

static void nf_vcpu_init(qemu_plugin_id_t id, unsigned int vcpu)
{
    if (vcpu >= NF_MAX_VCPUS) return;
    struct nf_regs *r = &nf.regs[vcpu];
    GArray *regs = qemu_plugin_get_registers();
    if (!regs) return;

    r->pc      = nf_find_reg(regs, "pc");
    r->priv    = nf_find_reg(regs, "priv");
    r->satp    = nf_find_reg(regs, "satp");
    r->scause  = nf_find_reg(regs, "scause");
    r->sepc    = nf_find_reg(regs, "sepc");
    r->stval   = nf_find_reg(regs, "stval");
    r->sstatus = nf_find_reg(regs, "sstatus");


    r->mcause  = nf_find_reg(regs, "mcause");
    r->mepc    = nf_find_reg(regs, "mepc");
    r->mtval   = nf_find_reg(regs, "mtval");
    r->sp      = nf_find_reg(regs, "sp");
    r->ra      = nf_find_reg(regs, "ra");
    static const char *anames[8] = {"a0","a1","a2","a3","a4","a5","a6","a7"};
    for (int i = 0; i < 8; i++) r->a[i] = nf_find_reg(regs, anames[i]);
    r->ready = (r->pc != NULL);
    g_array_free(regs, TRUE);

    g_mutex_lock(&nf.lock);
    uint32_t up = 1;
    nf_write_rec(NF_REC_VCPU, (uint8_t)vcpu, r->ready ? 0 : NF_F_NO_REGS,
                 qemu_plugin_u64_sum(nf.insn_count), &up, sizeof(up), NULL, 0);
    if (!r->ready) {
        nf_warn(0, "vCPU %u 的寄存器句柄取不到，该核的 PC/特权级将标记为 unknown", vcpu);
    }
    g_mutex_unlock(&nf.lock);
}












static GByteArray *nf_pagebuf;
static const uint8_t nf_zero_page[4096];

static void nf_release_snapshot_buffers(void)
{
    if (nf.shadow_pages) {
        for (uint32_t i = 0; i < nf.page_count; i++)
            g_free(nf.shadow_pages[i]);
        g_clear_pointer(&nf.shadow_pages, g_free);
    }
    g_clear_pointer(&nf.shadow_valid, g_free);
    g_clear_pointer(&nf.zbuf, g_free);
    nf.zbuf_cap = 0;
}

static bool nf_snapshot_page(unsigned int vcpu, uint64_t insn,
                             uint32_t page_index, const uint8_t *page,
                             uint32_t *changed)
{
    uint32_t ps = nf.page_size;
    bool zero = memcmp(page, nf_zero_page, ps) == 0;
    uint8_t *shadow_page = nf.shadow_pages[page_index];
    if (nf.shadow_valid[page_index] &&
        ((zero && !shadow_page) ||
         (!zero && shadow_page && memcmp(shadow_page, page, ps) == 0)))
        return true;

    uLongf clen = nf.zbuf_cap;
    int zrc = compress2(nf.zbuf, &clen, page, ps, 1);
    const void *body;
    size_t body_len;
    uint32_t rflags;
    if (zrc == Z_OK && clen < ps) {
        body = nf.zbuf;
        body_len = clen;
        rflags = NF_F_ZLIB;
    } else {
        body = page;
        body_len = ps;
        rflags = 0;
    }

    if (nf.ram_bytes + body_len > nf.max_ram_bytes) {
        nf.truncated = true;
        nf_warn(insn, "物理内存快照达到 %"PRIu64" 字节上限，后续快照被截断；"
                      "请调大 maxram= 或调稀 snap=", nf.max_ram_bytes);
        return false;
    }

    struct nf_pl_rampage pg = { .page_index = page_index, .raw_len = ps };
    nf_write_rec(NF_REC_RAMPAGE, (uint8_t)vcpu, rflags, insn,
                 &pg, sizeof(pg), body, body_len);
    if (zero) {
        g_clear_pointer(&nf.shadow_pages[page_index], g_free);
    } else {
        if (!shadow_page) {
            shadow_page = g_try_malloc(ps);
            if (!shadow_page) nf_die("分配物理页影子副本失败");
            nf.shadow_pages[page_index] = shadow_page;
        }
        memcpy(shadow_page, page, ps);
    }
    nf.shadow_valid[page_index] = true;
    nf.ram_bytes += body_len;
    (*changed)++;
    return true;
}

static void nf_snapshot(unsigned int vcpu, uint64_t insn)
{
    if (!nf.shadow_pages) return;

    uint64_t snap_seq = nf.n_snapshots++;
    uint32_t changed = 0;
    uint32_t ps = nf.page_size;


    long mark_pos = ftell(nf.out);
    struct nf_pl_snapmark mark = {
        .snap_seq = snap_seq, .ram_base = nf.ram_base,
        .page_size = ps, .pages_changed = 0, .pages_total = nf.page_count,
    };
    nf_write_rec(NF_REC_SNAPMARK, (uint8_t)vcpu, 0, insn, &mark, sizeof(mark), NULL, 0);

    uint32_t read_fail = 0;
    const uint32_t chunk_pages = 64;
    gint64 started_us = g_get_monotonic_time();
    for (uint32_t base = 0; base < nf.page_count && !nf.truncated;
         base += chunk_pages) {
        uint32_t pages = MIN(chunk_pages, nf.page_count - base);
        size_t chunk_len = (size_t)pages * ps;
        uint64_t pa = nf.ram_base + (uint64_t)base * ps;

        g_byte_array_set_size(nf_pagebuf, 0);
        nf.snapshot_reads++;
        bool chunk_ok = qemu_plugin_read_memory_hwaddr(pa, nf_pagebuf, chunk_len)
                        == QEMU_PLUGIN_HWADDR_OPERATION_OK
                     && nf_pagebuf->len >= chunk_len;
        if (chunk_ok) {
            for (uint32_t j = 0; j < pages && !nf.truncated; j++) {
                if (!nf_snapshot_page(vcpu, insn, base + j,
                                      nf_pagebuf->data + (size_t)j * ps,
                                      &changed))
                    break;
            }
            continue;
        }

        /* Preserve per-page failure reporting when a larger read is rejected. */
        nf.snapshot_fallbacks++;
        for (uint32_t j = 0; j < pages && !nf.truncated; j++) {
            uint32_t i = base + j;
            g_byte_array_set_size(nf_pagebuf, 0);
            pa = nf.ram_base + (uint64_t)i * ps;
            nf.snapshot_reads++;
            if (qemu_plugin_read_memory_hwaddr(pa, nf_pagebuf, ps)
                    != QEMU_PLUGIN_HWADDR_OPERATION_OK
                    || nf_pagebuf->len < ps) {
                read_fail++;
                continue;
            }
            nf_snapshot_page(vcpu, insn, i, nf_pagebuf->data, &changed);
        }
    }
    nf.snapshot_us += g_get_monotonic_time() - started_us;


    if (read_fail) {
        nf_warn(insn, "第 %"PRIu64" 次快照有 %u 页读不出来，该快照标记为不完整",
                snap_seq, read_fail);
    }


    long end_pos = ftell(nf.out);
    mark.pages_changed = changed;
    if (fseek(nf.out, mark_pos, SEEK_SET) == 0) {
        struct nf_rec_hdr h = {
            .type = NF_REC_SNAPMARK, .cpu = (uint8_t)vcpu,
            .len = sizeof(mark), .insn = insn,
            .flags = (nf.truncated ? NF_F_TRUNCATED : 0u)
                   | (read_fail ? NF_F_INCOMPLETE : 0u),
        };
        fwrite(&h, sizeof(h), 1, nf.out);
        fwrite(&mark, sizeof(mark), 1, nf.out);
        fseek(nf.out, end_pos, SEEK_SET);
    }
    if (nf.truncated) nf_release_snapshot_buffers();
}








static void nf_emit_sample(unsigned int vcpu, uint64_t insn)
{
    struct nf_regs *r = &nf.regs[vcpu < NF_MAX_VCPUS ? vcpu : 0];
    struct nf_pl_sample s = {0};
    uint32_t flags = 0;
    uint64_t v;

    if (nf_read_reg(vcpu, r->pc, &v)) s.pc = v; else flags |= NF_F_NO_REGS;
    if (nf_read_reg(vcpu, r->priv, &v)) s.priv = (uint32_t)v; else flags |= NF_F_NO_REGS;
    if (nf_read_reg(vcpu, r->satp, &v)) s.satp = v; else flags |= NF_F_NO_CSR;
    if (nf_read_reg(vcpu, r->sstatus, &v)) s.sstatus = v; else flags |= NF_F_NO_CSR;

    nf_write_rec(NF_REC_SAMPLE, (uint8_t)vcpu, flags, insn, &s, sizeof(s), NULL, 0);
    nf.n_samples++;
}

static void nf_finish(void);

static void nf_tb_check(unsigned int vcpu, void *udata)
{
    uint64_t insn = nf.ncpus == 1
                    ? qemu_plugin_u64_get(nf.insn_count, vcpu)
                    : qemu_plugin_u64_sum(nf.insn_count);


    if (nf.max_insn && insn >= nf.max_insn) {
        nf_finish();
        return;
    }

    if (insn < nf.next_sample && insn < nf.next_snap) return;

    g_mutex_lock(&nf.lock);
    if (nf.sample_every && insn >= nf.next_sample) {
        nf.next_sample = insn + nf.sample_every;
        nf_emit_sample(vcpu, insn);
    }
    if (nf.snap_every) {
        bool crossed_start = (!nf.start_snap_done && nf.snap_start
                              && insn >= nf.snap_start);
        if (crossed_start || insn >= nf.next_snap) {
            uint64_t iv = (insn >= nf.snap_start) ? nf.snap_every
                                                  : nf.boot_snap_every;
            if (!iv) iv = nf.snap_every;
            nf.next_snap = insn + iv;
            if (crossed_start) nf.start_snap_done = true;
            nf_snapshot(vcpu, insn);
        }
    }
    g_mutex_unlock(&nf.lock);
}














static void nf_discon(qemu_plugin_id_t id, unsigned int vcpu,
                      enum qemu_plugin_discon_type type,
                      uint64_t from_pc, uint64_t to_pc)
{
    struct nf_regs *r = &nf.regs[vcpu < NF_MAX_VCPUS ? vcpu : 0];
    struct nf_pl_discon d = {
        .discon_type = (uint32_t)type, .from_pc = from_pc, .to_pc = to_pc,
    };
    uint32_t flags = 0;
    uint64_t v;

    if (nf_read_reg(vcpu, r->priv, &v)) d.priv = (uint32_t)v; else flags |= NF_F_NO_REGS;
    if (nf_read_reg(vcpu, r->scause, &v)) d.scause = v; else flags |= NF_F_NO_CSR;
    if (nf_read_reg(vcpu, r->sepc, &v)) d.sepc = v; else flags |= NF_F_NO_CSR;
    if (nf_read_reg(vcpu, r->stval, &v)) d.stval = v; else flags |= NF_F_NO_CSR;
    if (nf_read_reg(vcpu, r->satp, &v)) d.satp = v; else flags |= NF_F_NO_CSR;
    if (nf_read_reg(vcpu, r->sstatus, &v)) d.sstatus = v; else flags |= NF_F_NO_CSR;
    if (nf_read_reg(vcpu, r->mcause, &v)) d.mcause = v; else flags |= NF_F_NO_MCSR;
    if (nf_read_reg(vcpu, r->mepc, &v))   d.mepc   = v; else flags |= NF_F_NO_MCSR;
    if (nf_read_reg(vcpu, r->mtval, &v))  d.mtval  = v; else flags |= NF_F_NO_MCSR;
    if (nf_read_reg(vcpu, r->sp, &v)) d.sp = v;
    for (int i = 0; i < 8; i++) {
        if (nf_read_reg(vcpu, r->a[i], &v)) d.a[i] = v; else flags |= NF_F_NO_REGS;
    }

    uint64_t insn = qemu_plugin_u64_sum(nf.insn_count);
    g_mutex_lock(&nf.lock);
    nf_write_rec(NF_REC_DISCON, (uint8_t)vcpu, flags, insn, &d, sizeof(d), NULL, 0);
    nf.n_discons++;
    g_mutex_unlock(&nf.lock);
}












static void nf_watch_hit(unsigned int vcpu, void *udata)
{
    uint32_t wid = (uint32_t)(uintptr_t)udata;
    struct nf_regs *r = &nf.regs[vcpu < NF_MAX_VCPUS ? vcpu : 0];
    struct nf_pl_watchpc w = { .watch_id = wid };
    uint32_t flags = 0;
    uint64_t v;












    if (wid < nf.n_watches) {
        struct nf_watch *cfg = &nf.watches[wid];
        if (cfg->rate > 1 && !cfg->snap && !cfg->nftrace) {
            uint64_t n = __atomic_fetch_add(&cfg->hits, 1, __ATOMIC_RELAXED);
            if (n % cfg->rate) {
                __atomic_fetch_add(&nf.n_watch_drops, 1, __ATOMIC_RELAXED);
                return;
            }
        }
        w.pc = cfg->addr;
    }
    if (nf_read_reg(vcpu, r->priv, &v)) w.priv = (uint32_t)v; else flags |= NF_F_NO_REGS;
    if (nf_read_reg(vcpu, r->satp, &v)) w.satp = v; else flags |= NF_F_NO_CSR;
    if (nf_read_reg(vcpu, r->sp, &v)) w.sp = v;
    if (nf_read_reg(vcpu, r->ra, &v)) w.ra = v;
    for (int i = 0; i < 8; i++) {
        if (nf_read_reg(vcpu, r->a[i], &v)) w.a[i] = v; else flags |= NF_F_NO_REGS;
    }

    uint64_t insn = qemu_plugin_u64_sum(nf.insn_count);
    g_mutex_lock(&nf.lock);
    nf_write_rec(NF_REC_WATCHPC, (uint8_t)vcpu, flags, insn, &w, sizeof(w), NULL, 0);
    nf.n_watch_hits++;










    if (wid < nf.n_watches && nf.watches[wid].nftrace) {
        uint64_t ptr = w.a[0];
        struct nf_nftrace_rec rec;
        GByteArray *buf = nf_vcpu_buf(vcpu);
        g_byte_array_set_size(buf, 0);
        if (ptr && qemu_plugin_read_memory_vaddr(ptr, buf, sizeof(rec))
                && buf->len == sizeof(rec)) {
            memcpy(&rec, buf->data, sizeof(rec));
            nf_write_rec(NF_REC_NFTRACE, (uint8_t)vcpu, 0, insn,
                         &rec, sizeof(rec), NULL, 0);
            nf.n_nftrace++;
        } else {
            nf.n_nftrace_fail++;
        }
    }





    if (wid < nf.n_watches && nf.watches[wid].snap && nf.snap_every) {
        bool go = true;
        if (nf.watches[wid].throttle) {




            if (nf.n_ev_snaps >= nf.ev_snap_max) go = false;
            else if (nf.last_ev_snap_insn &&
                     insn - nf.last_ev_snap_insn < nf.ev_snap_min) go = false;
            if (go) { nf.n_ev_snaps++; nf.last_ev_snap_insn = insn; }
        }
        if (go) nf_snapshot(vcpu, insn);
    }
    g_mutex_unlock(&nf.lock);
}

static void nf_tb_trans(qemu_plugin_id_t id, struct qemu_plugin_tb *tb)
{
    size_t n = qemu_plugin_tb_n_insns(tb);


    for (size_t i = 0; i < n; i++) {
        struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, i);
        qemu_plugin_register_vcpu_insn_exec_inline_per_vcpu(
            insn, QEMU_PLUGIN_INLINE_ADD_U64, nf.insn_count, 1);

        if (nf.watch_by_addr) {
            uint64_t va = qemu_plugin_insn_vaddr(insn);
            gpointer hit = g_hash_table_lookup(nf.watch_by_addr, GUINT_TO_POINTER(va));
            if (hit) {
                uint32_t wid = GPOINTER_TO_UINT(hit) - 1;
                qemu_plugin_register_vcpu_insn_exec_cb(
                    insn, nf_watch_hit, QEMU_PLUGIN_CB_R_REGS,
                    (void *)(uintptr_t)wid);
            }
        }
    }


    if (nf.sample_every || nf.snap_every || nf.max_insn) {
        qemu_plugin_register_vcpu_tb_exec_cb(tb, nf_tb_check,
                                             QEMU_PLUGIN_CB_NO_REGS, NULL);
    }
}










static void nf_vcpu_exit(qemu_plugin_id_t id, unsigned int vcpu)
{
    g_mutex_lock(&nf.lock);
    uint64_t insn = qemu_plugin_u64_sum(nf.insn_count);
    if (nf.snap_every && !nf.final_snap_done) {
        nf.final_snap_done = true;
        nf_snapshot(vcpu, insn);
    }
    uint32_t down = 0;
    nf_write_rec(NF_REC_VCPU, (uint8_t)vcpu, 0, insn, &down, sizeof(down), NULL, 0);
    g_mutex_unlock(&nf.lock);
}

static void nf_vcpu_idle(qemu_plugin_id_t id, unsigned int vcpu)
{
    uint32_t kind = 0;   /* 0 = idle */
    g_mutex_lock(&nf.lock);
    nf_write_rec(NF_REC_IDLE, (uint8_t)vcpu, 0,
                 qemu_plugin_u64_sum(nf.insn_count), &kind, sizeof(kind), NULL, 0);
    g_mutex_unlock(&nf.lock);
}

static void nf_vcpu_resume(qemu_plugin_id_t id, unsigned int vcpu)
{
    uint32_t kind = 1;   /* 1 = resume */
    g_mutex_lock(&nf.lock);
    nf_write_rec(NF_REC_IDLE, (uint8_t)vcpu, 0,
                 qemu_plugin_u64_sum(nf.insn_count), &kind, sizeof(kind), NULL, 0);
    g_mutex_unlock(&nf.lock);
}










static void nf_finish(void)
{
    g_mutex_lock(&nf.lock);
    if (!nf.out) { g_mutex_unlock(&nf.lock); return; }
    uint64_t insn = qemu_plugin_u64_sum(nf.insn_count);







    struct nf_pl_end e = {
        .total_insns = insn,
        .snapshots = nf.n_snapshots,
        .discons = nf.n_discons,
        .samples = nf.n_samples,
        .watch_hits = nf.n_watch_hits,
        .ram_bytes = nf.ram_bytes,
        .truncated = nf.truncated ? 1u : 0u,
        .watch_drops = nf.n_watch_drops,
    };
    nf_meta("nf.snapshot_reads=%"PRIu64, nf.snapshot_reads);
    nf_meta("nf.snapshot_fallbacks=%"PRIu64, nf.snapshot_fallbacks);
    nf_meta("nf.snapshot_us=%"PRIu64, nf.snapshot_us);
    nf_write_rec(NF_REC_END, 0, nf.truncated ? NF_F_TRUNCATED : 0, insn,
                 &e, sizeof(e), NULL, 0);
    fflush(nf.out);
    fclose(nf.out);
    nf.out = NULL;
    g_mutex_unlock(&nf.lock);

    fprintf(stderr,
            "[nodefusion-plugin] 结束：指令 %"PRIu64"，快照 %"PRIu64" 次，"
            "异常/中断 %"PRIu64" 次，采样 %"PRIu64" 次，watch 命中 %"PRIu64" 次，"
            "watch 限流丢弃 %"PRIu64" 次，"
            "内存快照 %.1f MiB，guest 语义 %"PRIu64" 条（读失败 %"PRIu64"）%s\n",
            insn, nf.n_snapshots, nf.n_discons, nf.n_samples, nf.n_watch_hits,
            nf.n_watch_drops,
            nf.ram_bytes / 1048576.0, nf.n_nftrace, nf.n_nftrace_fail,
            nf.truncated ? "（已截断）" : "");
}

static void nf_atexit(qemu_plugin_id_t id, void *p)
{



















    nf_finish();
}





static uint64_t nf_parse_u64(const char *s, const char *what)
{
    char *end = NULL;
    errno = 0;
    uint64_t v = g_ascii_strtoull(s, &end, 0);
    if (errno || end == s || (end && *end)) {
        nf_die("参数 %s 的值 '%s' 不是合法整数", what, s);
    }
    return v;
}





static void nf_load_watches(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) nf_die("打不开 watch 列表 '%s'：%s", path, strerror(errno));

    GArray *arr = g_array_new(FALSE, TRUE, sizeof(struct nf_watch));
    char line[512];
    while (fgets(line, sizeof(line), f)) {
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '#' || *p == '\n' || *p == '\0') continue;
        char *sep = NULL;
        uint64_t addr = g_ascii_strtoull(p, &sep, 0);
        if (!sep || sep == p) continue;
        while (*sep == ' ' || *sep == '\t') sep++;
        char *nl = strpbrk(sep, "\r\n");
        if (nl) *nl = '\0';












        bool snap = false, throttle = false, nftrace = false;
        uint32_t rate = 0;
        while (*sep == '@') {
            char *colon = strchr(sep, ':');
            if (!colon) break;
            *colon = '\0';
            const char *tag = sep + 1;
            if (!strcmp(tag, "snap")) snap = true;

            else if (!strcmp(tag, "esnap")) { snap = true; throttle = true; }

            else if (!strcmp(tag, "nft")) nftrace = true;

            else if (tag[0] == 'r' && tag[1])
                rate = (uint32_t)g_ascii_strtoull(tag + 1, NULL, 10);
            else





                nf_die("watch 列表第 '%s' 行有认不出的标记 '@%s:'", p, tag);
            sep = colon + 1;
        }
        struct nf_watch w = { .addr = addr, .name = g_strdup(sep), .snap = snap,
                              .throttle = throttle, .nftrace = nftrace,
                              .rate = rate, .hits = 0 };
        g_array_append_val(arr, w);
    }
    fclose(f);

    nf.n_watches = arr->len;
    nf.watches = (struct nf_watch *)g_array_free(arr, FALSE);
    nf.watch_by_addr = g_hash_table_new(g_direct_hash, g_direct_equal);
    for (unsigned i = 0; i < nf.n_watches; i++) {
        g_hash_table_insert(nf.watch_by_addr,
                            GUINT_TO_POINTER(nf.watches[i].addr),
                            GUINT_TO_POINTER(i + 1));
    }
}

QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id,
                                           const qemu_info_t *info,
                                           int argc, char **argv)
{
    const char *out_path = NULL;
    const char *watch_path = NULL;

    nf.sample_every   = 200000;
    nf.snap_every     = 50000000;
    nf.ram_base       = 0x80000000ULL;
    nf.ram_size       = 128ULL << 20;
    nf.page_size      = 4096;
    nf.max_ram_bytes  = 1024ULL << 20;

    for (int i = 0; i < argc; i++) {
        char **kv = g_strsplit(argv[i], "=", 2);
        if (!kv[0] || !kv[1]) { g_strfreev(kv); nf_die("参数 '%s' 需要 key=value 形式", argv[i]); }
        if (!strcmp(kv[0], "out"))          out_path = g_strdup(kv[1]);
        else if (!strcmp(kv[0], "watch"))   watch_path = g_strdup(kv[1]);
        else if (!strcmp(kv[0], "sample"))  nf.sample_every = nf_parse_u64(kv[1], "sample");
        else if (!strcmp(kv[0], "snap"))    nf.snap_every = nf_parse_u64(kv[1], "snap");
        else if (!strcmp(kv[0], "bootsnap")) nf.boot_snap_every = nf_parse_u64(kv[1], "bootsnap");
        else if (!strcmp(kv[0], "evsnapmin")) nf.ev_snap_min = nf_parse_u64(kv[1], "evsnapmin");
        else if (!strcmp(kv[0], "evsnapmax")) nf.ev_snap_max = nf_parse_u64(kv[1], "evsnapmax");
        else if (!strcmp(kv[0], "snapstart")) nf.snap_start = nf_parse_u64(kv[1], "snapstart");
        else if (!strcmp(kv[0], "rambase")) nf.ram_base = nf_parse_u64(kv[1], "rambase");
        else if (!strcmp(kv[0], "ramsize")) nf.ram_size = nf_parse_u64(kv[1], "ramsize");
        else if (!strcmp(kv[0], "maxram"))  nf.max_ram_bytes = nf_parse_u64(kv[1], "maxram");
        else if (!strcmp(kv[0], "maxinsn")) nf.max_insn = nf_parse_u64(kv[1], "maxinsn");
        else nf_die("未知参数 '%s'", kv[0]);
        g_strfreev(kv);
    }

    if (!out_path) nf_die("必须指定 out=<轨迹文件路径>");





    if (nf.ev_snap_min == 0) nf.ev_snap_min = 2000000;
    if (nf.ev_snap_max == 0) nf.ev_snap_max = 120;

    nf.out = fopen(out_path, "wb");
    if (!nf.out) nf_die("打不开输出文件 '%s'：%s", out_path, strerror(errno));
    setvbuf(nf.out, NULL, _IOFBF, 1 << 20);


    if (fwrite(NF_MAGIC, 8, 1, nf.out) != 1) nf_die("写文件头失败");
    uint32_t ver = NF_FORMAT_VER;
    if (fwrite(&ver, sizeof(ver), 1, nf.out) != 1) nf_die("写版本失败");
    uint32_t hdr_size = (uint32_t)sizeof(struct nf_rec_hdr);
    if (fwrite(&hdr_size, sizeof(hdr_size), 1, nf.out) != 1) nf_die("写头长度失败");

    g_mutex_init(&nf.lock);
    for (unsigned int i = 0; i < NF_MAX_VCPUS; i++)
        nf_regbuf[i] = g_byte_array_sized_new(64);
    nf_pagebuf = g_byte_array_sized_new(nf.page_size);
    nf.writebuf = g_byte_array_sized_new(sizeof(struct nf_rec_hdr) + nf.page_size);

    nf.sb = qemu_plugin_scoreboard_new(sizeof(uint64_t));
    nf.insn_count = qemu_plugin_scoreboard_u64(nf.sb);
    nf.ncpus = info->system.max_vcpus;

    nf.page_count = (uint32_t)(nf.ram_size / nf.page_size);
    if (nf.snap_every) {
        nf.shadow_pages = g_try_malloc0((size_t)nf.page_count * sizeof(uint8_t *));
        nf.shadow_valid = g_try_malloc0((size_t)nf.page_count * sizeof(bool));
        if (!nf.shadow_pages || !nf.shadow_valid) {
            nf_die("分配 %u 页影子页索引失败", nf.page_count);
        }
        nf.zbuf_cap = compressBound(nf.page_size);
        nf.zbuf = g_try_malloc(nf.zbuf_cap);
        if (!nf.zbuf) nf_die("分配页压缩缓冲失败");
    }

    if (watch_path) nf_load_watches(watch_path);

    nf.next_sample = nf.sample_every ? nf.sample_every : UINT64_MAX;
    if (!nf.snap_every) {
        nf.next_snap = UINT64_MAX;
    } else {
        nf.next_snap = nf.boot_snap_every ? nf.boot_snap_every : nf.snap_every;
    }

    nf_meta("nodefusion.plugin_api=%d", QEMU_PLUGIN_VERSION);
    nf_meta("qemu.plugin_api_min=%d", info->version.min);
    nf_meta("qemu.plugin_api_cur=%d", info->version.cur);
    nf_meta("qemu.target=%s", info->target_name ? info->target_name : "unknown");
    nf_meta("qemu.smp=%d", info->system.smp_vcpus);
    nf_meta("qemu.max_vcpus=%d", info->system.max_vcpus);
    nf_meta("nf.sample_every=%"PRIu64, nf.sample_every);
    nf_meta("nf.snap_every=%"PRIu64, nf.snap_every);
    nf_meta("nf.boot_snap_every=%"PRIu64, nf.boot_snap_every);
    nf_meta("nf.snap_start=%"PRIu64, nf.snap_start);
    nf_meta("nf.ram_base=0x%"PRIx64, nf.ram_base);
    nf_meta("nf.ram_size=0x%"PRIx64, nf.ram_size);
    nf_meta("nf.page_size=%u", nf.page_size);
    nf_meta("nf.max_ram_bytes=%"PRIu64, nf.max_ram_bytes);
    nf_meta("nf.watches=%u", nf.n_watches);
    nf_meta("nf.ev_snap_min=%"PRIu64, nf.ev_snap_min);
    nf_meta("nf.ev_snap_max=%"PRIu64, nf.ev_snap_max);

    {
        unsigned nft = 0;
        for (unsigned i = 0; i < nf.n_watches; i++) if (nf.watches[i].nftrace) nft++;
        nf_meta("nf.nftrace_watches=%u", nft);
    }

    qemu_plugin_register_vcpu_init_cb(id, nf_vcpu_init);
    qemu_plugin_register_vcpu_exit_cb(id, nf_vcpu_exit);
    qemu_plugin_register_vcpu_tb_trans_cb(id, nf_tb_trans);
    qemu_plugin_register_vcpu_discon_cb(id, QEMU_PLUGIN_DISCON_ALL, nf_discon);
    qemu_plugin_register_vcpu_idle_cb(id, nf_vcpu_idle);
    qemu_plugin_register_vcpu_resume_cb(id, nf_vcpu_resume);
    qemu_plugin_register_atexit_cb(id, nf_atexit, NULL);

    fprintf(stderr, "[nodefusion-plugin] 已挂载：out=%s sample=%"PRIu64
                    " snap=%"PRIu64" watches=%u\n",
            out_path, nf.sample_every, nf.snap_every, nf.n_watches);
    nf.started = true;
    return 0;
}
