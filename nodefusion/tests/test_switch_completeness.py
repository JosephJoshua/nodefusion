from types import SimpleNamespace as NS

import pytest

from nodefusion.host.analyze import Analysis
from nodefusion.model.resolve import ABSENT, PRESENT, UNDECODABLE


@pytest.mark.parametrize('context_state', [None, ABSENT, UNDECODABLE, PRESENT])
def test_total_process_table_requires_decoded_contexts_for_scheduler_inference(context_state):
    fields = [] if context_state is None else [NS(role='sched_context', state=context_state)]
    process = NS(name='process', sources=[NS(completeness='total', reason=None)], fields=fields)
    entities = NS(entity_for=lambda *args, **kwargs: NS(name='process'),
                  res=NS(entities=[process]))
    analysis = NS(decoder=NS(entities=entities))
    assert Analysis._tasks_exhaustive(analysis) is (True if context_state == PRESENT else None)


def test_thread_contexts_can_supply_process_scheduler_identity():
    source = NS(completeness='total', reason=None)
    process = NS(name='process', sources=[source], fields=[NS(role='sched_context', state=ABSENT)])
    thread = NS(name='thread', sources=[source], fields=[NS(role='sched_context', state=PRESENT)])
    entities = NS(entity_for=lambda *args, **kwargs: NS(name='process'),
                  res=NS(entities=[process, thread]))
    analysis = NS(decoder=NS(entities=entities))
    assert Analysis._tasks_exhaustive(analysis) is True
