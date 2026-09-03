"""One-off: reatribui perfis de voz cadastrados ANTES da autenticação real
(storage/voices/<participant_id>/, sem dono) para uma conta já existente.

Pré-requisito: a conta já precisa existir — este script NUNCA cria conta
nem lida com senha, só resolve o user_id a partir do e-mail informado
(registre primeiro via POST /auth/register) e move os diretórios.

Identifica candidato a perfil legado pela presença de profile.json DIRETO
sob storage/voices/<algo>/ (layout antigo). Uma pasta storage/voices/<user_id>/
já migrada nunca tem profile.json nesse nível — só participant_id/profile.json
um nível abaixo — então rodar o script de novo é seguro (idempotente, não
tenta mover o que já foi movido).

Uso:
    python -m scripts.migrate_voices_to_user --email leandro.freitas@ifg.edu.br
    python -m scripts.migrate_voices_to_user --email ... --dry-run   # só lista
"""
import argparse
import shutil
import sys
from pathlib import Path

from app.config import get_settings
from app.repositories.user_repository import get_user_repository


def _perfis_legados(voices_root: Path) -> list:
    return sorted(
        child for child in voices_root.iterdir() if child.is_dir() and (child / "profile.json").is_file()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True, help="E-mail da conta já registrada que vai receber os perfis.")
    parser.add_argument("--dry-run", action="store_true", help="Só lista o que seria movido, sem mover nada.")
    args = parser.parse_args()

    user = get_user_repository().get_user_by_email(args.email)
    if user is None:
        print(
            f"Nenhuma conta encontrada para {args.email}. Registre primeiro via POST /auth/register.",
            file=sys.stderr,
        )
        return 1

    voices_root = Path(get_settings().storage_root) / "voices"
    if not voices_root.is_dir():
        print(f"{voices_root} não existe — nada para migrar.")
        return 0

    candidatos = _perfis_legados(voices_root)
    if not candidatos:
        print("Nenhum perfil legado encontrado (nada com profile.json direto sob storage/voices/) — nada a fazer.")
        return 0

    destino = voices_root / user.id
    print(f"Conta destino: {args.email} (user_id={user.id})")
    print(f"{len(candidatos)} perfil(is) legado(s) encontrado(s):")
    for pasta in candidatos:
        print(f"  - {pasta.name} -> storage/voices/{user.id}/{pasta.name}")

    if args.dry_run:
        print("\n--dry-run: nada foi movido.")
        return 0

    destino.mkdir(parents=True, exist_ok=True)
    for pasta in candidatos:
        shutil.move(str(pasta), str(destino / pasta.name))

    print(f"\n{len(candidatos)} perfil(is) movido(s) para storage/voices/{user.id}/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
