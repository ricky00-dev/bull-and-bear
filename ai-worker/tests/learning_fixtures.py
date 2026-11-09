from bullbear.schemas import StatementAnalysis, ModeratorAnalysis


def with_analysis(statement):
    return statement.model_copy(update={'analysis': StatementAnalysis(
        outlook='HOLD', interpretations=[dict(evidence_ref=e.ref, expected_outcome='HOLD',
            assumptions=['관측된 관계가 유지된다는 가정'], limitations=['미래 관계는 미확인'])
            for e in statement.evidence], rebuttal=None, closing=None)})


def moderator_analysis():
    return ModeratorAnalysis(common_ground=[], core_issues=['상대수익 관계의 지속 여부'],
        disagreements=[], unverified=['미래 수급'], outlook_basis=['관측된 가격을 조건부 해석'],
        outlook_limits=['미래 관계는 미확인'], key_interpretation_ids=[])
