
from __future__ import annotations

ROLES: dict[str, str] = {
    "id": "人称呼这个东西时用的那个号（pid / tid / vm_id …）",
    "name": "给人看的名字",
    "state": "调度或生命周期状态",
    "address_space_root": "地址空间根：页表根物理地址、satp 的值",
    "priority": "调度优先级",
    "exit_code": "退出码",
    "trap_context": "保存用户态寄存器的那块内存的地址",
    #     xv6     struct proc.context                    +104
    #     ArceOS  axtask::task::TaskInner.ctx            +120
    #     rCore   os::task::task::TaskControlBlockInner.task_cx  +120
    "sched_context": "切换任务时保存内核态寄存器的那块内存的地址",
}


def check_role(role: str | None, where: str) -> None:
    if role is None or role in ROLES:
        return
    known = "、".join(sorted(ROLES))
    raise ValueError(
        f"{where}：不认识的角色 {role!r}。认识的有：{known}。"
        f"角色是**闭集** —— 写错了不报错的话，UI 按角色取值会取到空，"
        f"而空跟'这个内核本来就没有这个字段'长得一样，谁也发现不了。"
        f"确实需要新角色的话，去 nodefusion/model/roles.py 里加。")
