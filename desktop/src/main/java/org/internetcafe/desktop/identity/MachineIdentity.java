package org.internetcafe.desktop.identity;

import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.cert.X509Certificate;

public record MachineIdentity(
    PrivateKey privateKey,
    PublicKey publicKey,
    X509Certificate certificate,
    PublicJwk publicJwk,
    String thumbprint) {}
