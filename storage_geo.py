from __future__ import annotations

import mimetypes
import os
import re
import unicodedata
import uuid
from functools import lru_cache

import boto3
from botocore.config import Config


R2_ENDPOINT = os.getenv("GEO_R2_ENDPOINT", "").strip()
R2_BUCKET = os.getenv("GEO_R2_BUCKET", "").strip()
R2_ACCESS_KEY_ID = os.getenv("GEO_R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("GEO_R2_SECRET_ACCESS_KEY", "").strip()


def _validar_configuracao():
    faltando = []
    if not R2_ENDPOINT:
        faltando.append("GEO_R2_ENDPOINT")
    if not R2_BUCKET:
        faltando.append("GEO_R2_BUCKET")
    if not R2_ACCESS_KEY_ID:
        faltando.append("GEO_R2_ACCESS_KEY_ID")
    if not R2_SECRET_ACCESS_KEY:
        faltando.append("GEO_R2_SECRET_ACCESS_KEY")
    if faltando:
        raise RuntimeError(
            "Configuracao do Cloudflare R2 incompleta. Defina no Windows: "
            + ", ".join(faltando)
        )


@lru_cache(maxsize=1)
def cliente_r2():
    _validar_configuracao()
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _nome_seguro(nome: str) -> str:
    nome = os.path.basename(str(nome or "arquivo"))
    base, ext = os.path.splitext(nome)
    base = unicodedata.normalize("NFKD", base)
    base = base.encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    if not base:
        base = "arquivo"
    ext = re.sub(r"[^A-Za-z0-9.]+", "", ext.lower())
    return f"{base}{ext}"


def caminho_storage(caminho_objeto: str) -> str:
    return f"r2:{caminho_objeto}"


def upload_documento(
    projeto_id: int,
    numero_projeto: str,
    nome_arquivo: str,
    conteudo: bytes,
    content_type: str | None = None,
) -> str:
    cliente = cliente_r2()
    numero_seguro = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        str(numero_projeto or projeto_id).strip(),
    ).strip("._-") or str(projeto_id)
    nome_seguro = _nome_seguro(nome_arquivo)
    caminho = (
        f"projetos/{int(projeto_id)}_{numero_seguro}/"
        f"{uuid.uuid4().hex}_{nome_seguro}"
    )
    mime = content_type or mimetypes.guess_type(nome_arquivo)[0] or "application/octet-stream"
    cliente.put_object(
        Bucket=R2_BUCKET,
        Key=caminho,
        Body=conteudo,
        ContentType=mime,
        CacheControl="private, max-age=300",
    )
    return caminho


def remover_documento(caminho_objeto: str):
    cliente_r2().delete_object(
        Bucket=R2_BUCKET,
        Key=caminho_objeto,
    )


def criar_url_assinada(caminho_objeto: str, expires_in: int = 300) -> str:
    return cliente_r2().generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": R2_BUCKET, "Key": caminho_objeto},
        ExpiresIn=int(expires_in),
    )


def listar_objetos(prefixo: str = ""):
    resposta = cliente_r2().list_objects_v2(
        Bucket=R2_BUCKET,
        Prefix=prefixo,
    )
    return resposta.get("Contents", [])
