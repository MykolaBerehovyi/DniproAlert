import json
from dataclasses import dataclass

from app.enums import ThreatEnum
from app.prompts import DNIPRO_PROMPT, DNIPRO_VERIFIER_PROMPT

ANSWERS = {
    "Ні": None,
    "Відбій": ThreatEnum.CALM,
    "Так: червоний рівень": ThreatEnum.RED_LEVEL,
    "Так: шахеди": ThreatEnum.DRONES,
    "Так: балістика": ThreatEnum.BALLISTICS,
    "Так: комбінована атака": ThreatEnum.COMBINED,
}


@dataclass(frozen=True)
class Classification:
    preliminary: str
    final: str

    @property
    def threat(self):
        return ANSWERS[self.final]


async def classify(client, body: str, context: list, current: ThreatEnum, primary: str, verifier: str):
    active = current != ThreatEnum.CALM
    first = await client.responses.create(
        model=primary,
        input=(
            f"{DNIPRO_PROMPT}\nПОТОЧНИЙ СТАН ТРИВОГИ: {'АКТИВНА' if active else 'НЕАКТИВНА'}"
            f"\nІСТОРІЯ\n{json.dumps(context, ensure_ascii=False)}\nНОВЕ ПОВІДОМЛЕННЯ\n{body}"
        ),
    )
    preliminary = first.output_text.strip()[:2000]
    evidence = {
        "current_state": "active" if active else "inactive",
        "current_threat": current.value,
        "history": context,
        "new_message": body,
        "preliminary_answer": preliminary,
    }
    second = await client.responses.create(
        model=verifier,
        input=f"{DNIPRO_VERIFIER_PROMPT}\nВХІДНІ ДАНІ ДЛЯ ФІНАЛЬНОЇ ПЕРЕВІРКИ (JSON)\n{json.dumps(evidence, ensure_ascii=False)}",
    )
    final = second.output_text.strip()
    if final not in ANSWERS:
        raise ValueError("Verifier response outside the alert contract")
    return Classification(preliminary, final)
