# ST-DSK-01 · Prototipo de clave con TPM (SunMSCAPI)

Historia: HU-28 (#40) · Tarea: #96 · Equipo: Desktop

## Objetivo

Comprobar si la clave de firma del equipo puede vivir en el TPM de Windows, sin poder exportarse, usando solo el JDK (proveedor SunMSCAPI) y sin librerías nativas.

## Qué es SunMSCAPI

- Proveedor de seguridad incluido en el JDK para Windows. No existe en Linux ni en macOS.
- Expone el almacén de certificados del usuario como un `KeyStore` de tipo `Windows-MY`.
- La clave privada que entrega es un manejador hacia CryptoAPI/CNG: Java pide firmar y Windows firma. Con una clave no exportable, `getEncoded()` devuelve `null`: el material de la clave no sale del almacén.

## Qué no hace

- No crea claves dentro del TPM. La clave se crea fuera de Java con el proveedor "Microsoft Platform Crypto Provider" y Java la usa por alias.
- Solo Windows. En otros sistemas `TpmKeyPrototype.openWindowsStore()` lanza `UnsupportedOperationException`.

## Cómo crear la clave de prueba (PowerShell)

Comprobar que hay un TPM 2.0 listo (`TPM presente` y `Está listo para el almacenamiento`):

```powershell
tpmtool getdeviceinformation
```

Crear una clave RSA de 2048 bits no exportable en el TPM, con un certificado autofirmado en el almacén del usuario:

```powershell
New-SelfSignedCertificate -Subject "CN=internet-cafe-prototype" -FriendlyName "internet-cafe-prototype" -KeyAlgorithm RSA -KeyLength 2048 -KeyExportPolicy NonExportable -Provider "Microsoft Platform Crypto Provider" -CertStoreLocation Cert:/CurrentUser/My -NotAfter (Get-Date).AddYears(1)
```

Nota: con `-KeyAlgorithm ECDSA_nistP256` y el mismo proveedor, `New-SelfSignedCertificate` falló en el equipo de prueba (TPM 2.0) con `NTE_PROV_TYPE_NOT_DEF` (0x80090017). Con RSA funcionó.

Sin TPM, el proveedor `Microsoft Software Key Storage Provider` también crea claves no exportables, pero sin respaldo de hardware.

Para ver con qué proveedor quedó la clave:

```powershell
certutil -user -store My internet-cafe-prototype
```

Al terminar, borrar el certificado y su clave de prueba:

```powershell
Get-ChildItem Cert:/CurrentUser/My | Where-Object FriendlyName -eq "internet-cafe-prototype" | Remove-Item -DeleteKey
```

## Cómo ejecutar el prototipo

```powershell
$env:TPM_ALIAS = "internet-cafe-prototype"
gradle -p desktop cleanTest test --tests "*TpmKeyPrototypeTest" -i
```

La prueba `signsWithTheRealWindowsKey` abre `Windows-MY`, firma un reto con la clave del alias, verifica la firma con la clave pública del certificado y comprueba que la clave no es exportable. Sin la variable `TPM_ALIAS` (por ejemplo en el CI) esa prueba se omite.

## Resultado de la prueba

**Fecha de la prueba:** 2026-11-20

**Proveedor de la clave (certutil):** Proveedor = Microsoft Platform Crypto Provider

```text
tipo_de_clave=RSA
clase_de_clave=sun.security.mscapi.CPrivateKey
no_exportable=true
proveedor_de_firma=SunMSCAPI
firma_bytes=256
firma_verificada=true
promedio_ms_por_firma=279
```

## Conclusiones y siguientes pasos

- Si el resultado muestra `no_exportable=true` y `firma_verificada=true`, SunMSCAPI permite firmar con una clave del TPM sin exportarla, solo con el JDK.
- La clave del prototipo es RSA 2048 (firma `SHA256withRSA`). Si el contrato de firma del equipo exige ECDSA, hay que investigar cómo crear la clave ECC en el TPM por otra vía (por ejemplo `certutil` o CNG directamente), porque con `New-SelfSignedCertificate` no fue posible en el equipo de prueba.
- Depende de que el equipo tenga TPM 2.0 activo. Sin TPM habría que mantener la clave actual como alternativa.
- Integración sugerida (tarea aparte): poner la firma detrás de una interfaz `sign(byte[])`, con la clave actual como implementación por defecto y la del TPM como opción en Windows, y enrolar la clave pública en el servidor.
- Este prototipo no está conectado a `MachineIdentityStore` ni cambia el comportamiento de la aplicación.