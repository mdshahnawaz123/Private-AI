"""Compatibility status for the retired mock evaluator.

Real answer evaluation lives in intelligence.answer_evaluation and requires
independent gold cases plus actual authenticated pipeline/model outputs.
"""

def run_forensic_test_bg(project_id, document_id):
    raise RuntimeError('Status-only mock evaluation is disabled. Use intelligence.answer_evaluation with independently labelled cases and the real answer callback.')


def start_forensic_test(project_id, document_id):
    return {'status': 'disabled', 'message': 'The legacy mock runner cannot measure answer accuracy. Use a labelled real-model evaluation.'}


def get_forensic_status():
    return {'status': 'disabled', 'evaluation_kind': 'legacy_status_only_disabled',
            'answer_accuracy': None, 'total': 0, 'completed': 0,
            'passed': 0, 'failed': 0, 'current_question': '',
            'current_stage': 'Real-model labelled evaluation required', 'elapsed': 0}
