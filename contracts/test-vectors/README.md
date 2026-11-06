# Vectores de firma y firmador de referencia (SEC-08)

Contrato de la firma de peticiones del PC (HU-19). El firmador Java (DSK-12a) y el verificador
del backend deben producir y aceptar lo mismo que `firmador_referencia.py`.

Perfil: RFC 9421 `ecdsa-p256-sha256`, etiqueta `sig1`; Content-Digest sha-256 (RFC 9530) sobre bytes
UTF-8; `keyid` = huella JWK RFC 7638 (base64url); componentes `@method`, `@target-uri` y, solo con
cuerpo, `content-digest`; parametros `created`, `keyid`, `alg`, `nonce`; `@target-uri` sale de
`PUBLIC_API_BASE_URL` + ruta; firma `r||s` de 64 bytes en base64.

Casos: POST con cuerpo, cuerpo Unicode, GET sin cuerpo (sin Content-Digest) y clave con cero inicial
(x o y empieza en 0x00 y debe medir 32 bytes; recortarla cambia la huella).

La firma ECDSA no es determinista: compara `base_de_firma`, `content_digest`, `signature_input` y
`keyid` byte a byte, y VERIFICA la firma con `jwk_publica`. Las claves son solo de prueba.

Regenerar: `python contracts/test-vectors/generar_vectores.py`