# Repositories by corpus

The released dataset has 179 repositories. This page lists each one under the corpus it
was assigned when it was collected on 21–24 September 2026:

- **A** (81 repositories): 14.8% or more of the repository's pull requests and issues
  name one of the 90 PQC terms, so every issue, pull request and commit is collected.
- **B** (87 repositories): below 14.8%, so only issues and pull requests whose title or
  body names a term are collected, plus commits whose message names a term or that
  belong to a collected pull request.
- **C** (11 repositories): no pull requests or issues, so every commit is collected.

[Collecting a run](../README.md#collecting-a-run) explains how the share is measured,
and [COLLECTION.md](COLLECTION.md) gives the details.

The list comes from the `corpus` field of `repositories.jsonl` in Hugging Face revision
`4d72fb0` (SHA-256 `12738b2a1d297210b4cee88fe248a3b42b01bef4765fc5ad4310537e0a6d77f6`).
The patch-free view has the same file. To print it from a checkout of the release:

```bash
python3 -c "import json; [print(r['corpus'], r['repo']) for r in sorted((json.loads(l) for l in open('data/repositories.jsonl')), key=lambda r: (r['corpus'], r['repo'].lower()))]"
```

Replace `data/repositories.jsonl` with the path to your copy.

## Corpus A: everything collected (81 repositories)

- `acmert/kyber-polmul-hw`
- `aditisrinivas97/Crypto-Vinaigrette`
- `Anish-M-code/pqcrypt`
- `antontutoveanu/crystals-kyber-javascript`
- `Argyle-Software/dilithium`
- `Argyle-Software/kyber`
- `arnika-project/arnika`
- `backbone-hq/pqcrypto`
- `bcgit/bc-kotlin`
- `bcgit/bc-rust`
- `celabshq/libcrux`
- `chipsalliance/adams-bridge`
- `cloudflare/circl`
- `Colfenor/classic-mceliece-rust`
- `Comcast/CARAF`
- `crt26/PQC-LEO`
- `cyph/pqcrypto.js`
- `dajiaji/crystals-kyber-js`
- `Dashlane/pqc.js`
- `eclipse-keypont/crypto11`
- `FiloSottile/mlkem768`
- `fisherstevenk/crystals-kyber-ts`
- `GiacomoPope/Castryck-Decru-SageMath`
- `GiacomoPope/dilithium-py`
- `GiacomoPope/kyber-py`
- `GMUCERG/Dilithium`
- `grocid/libPQP`
- `iavofficial/IAV_quantumSAR`
- `integritychain/fips203`
- `integritychain/fips204`
- `isec-tugraz/Picnic`
- `itzmeanjan/falcon`
- `itzmeanjan/ml-dsa`
- `itzmeanjan/ml-kem`
- `jmlepisto/clatter`
- `jschanck/ntru`
- `kasperdi/SPHINCSPLUS-golang`
- `kuking/go-frodokem`
- `lwe-frodo/lwe-frodo`
- `microsoft/PQCrypto-LWEKE`
- `microsoft/PQCrypto-VPN`
- `mjosaarinen/py-acvp-pqc`
- `mthiim/dilithium-java`
- `mupq/pqm4`
- `open-quantum-safe/liboqs`
- `open-quantum-safe/liboqs-cpp`
- `open-quantum-safe/liboqs-go`
- `open-quantum-safe/liboqs-java`
- `open-quantum-safe/liboqs-python`
- `open-quantum-safe/liboqs-rust`
- `open-quantum-safe/openssh`
- `open-quantum-safe/oqs-demos`
- `open-quantum-safe/oqs-provider`
- `paulmillr/noble-post-quantum`
- `pornin/c-fn-dsa`
- `pornin/rust-fn-dsa`
- `pq-code-package/mldsa-native`
- `pq-code-package/mlkem-native`
- `pq-code-package/slhdsa-c`
- `pq-crystals/dilithium`
- `pq-crystals/kyber`
- `PQCMayo/MAYO-C`
- `pqcrypto-cn/PQMagic`
- `PQShield/nist-sigs-zoo`
- `Quantum-Blockchains/dilithium`
- `quininer/sarkara`
- `RustCrypto/KEMs`
- `safecrypto/libsafecrypto`
- `slh-dsa/sloth`
- `smuellerDD/leancrypto`
- `sphincs/sphincsplus`
- `SQISign/the-sqisign`
- `symbolicsoft/kyber-k2so`
- `terra-quantum-public/tq42-pqc-oss`
- `theQRL/qrllib`
- `thomwiggers/kemtls-experiment`
- `tniessen/node-pqclean`
- `Verified-zkEVM/VCVio`
- `wolfSSL/wolfCOSE`
- `XMSS/xmss-reference`
- `xuxu298/PQCAnalyzer`

## Corpus B: matching items only (87 repositories)

- `algorand/falcon`
- `amagioss/slv`
- `ameshkov/gocurl`
- `ANSSI-FR/MLA`
- `ARS4EVER/QSP`
- `authelia/authelia`
- `Avarok-Cybersecurity/Citadel-Protocol`
- `aws/aws-lc-rs`
- `aws/s2n-tls`
- `bcgit/bc-csharp`
- `bcgit/bc-java`
- `bcgit/pc-dart`
- `cabelo/libzupt`
- `cbomkit/cbomkit`
- `cbomkit/cbomkit-theia`
- `cbomkit/sonar-cryptography`
- `dajiaji/hpke-js`
- `eclipse-keysealer/k8s-kms-plugin`
- `emmansun/gmsm`
- `facebook/folly`
- `facebookincubator/fizz`
- `FinAegis/core-banking-prototype-laravel`
- `fisherstevenk/kyberJCE`
- `ForkbombEu/pqspread`
- `golang/go`
- `HcashOrg/hcashd`
- `hezhijie0327/ZJDNS`
- `ixian-platform/Spixi`
- `jedisct1/libsodium`
- `jiayaoqijia/eth2030`
- `junkurihara/rust-rpxy`
- `kubernetes/kubernetes`
- `lattice-complete/Lazarus`
- `leanEthereum/leanSpec`
- `LearningToSQI/SQISign-SageMath`
- `liesware/coherence`
- `litvinovtd/qeli`
- `LukaJCB/ts-mls`
- `Mastercard/pkcs11-tools`
- `MHSanaei/3x-ui`
- `n42blockchain/N42-rs`
- `Neptune-Crypto/twenty-first`
- `NethermindEth/zinc-plus`
- `number571/go-peer`
- `number571/hidden-lake`
- `openHiTLS/openHiTLS`
- `openssl/openssl`
- `orion-rs/orion`
- `osbytes/crypt.fyi`
- `OWASP/openshield`
- `PentHertz/LUKSbox`
- `pike00/coldkey`
- `QRCS-CORP/CEX`
- `Quantova/QCore.rs`
- `quincy-rs/quincy`
- `randombit/botan`
- `rosenpass/rosenpass`
- `ruslan-ilesik/poqeth`
- `RustCrypto/elliptic-curves`
- `RustCrypto/signatures`
- `sbom-tool/sbom-tools`
- `sebastienrousseau/kyberlib`
- `slothy-optimizer/slothy`
- `SRI-CSL/Bliss`
- `Sumitchongder/Quantum-Resistant-Module-Lattice-Cryptography`
- `swisslite/Kryptos`
- `TheMaxMur/RS-Key`
- `theQRL/QRL`
- `theQRL/qrl-wallet`
- `tidecoin-old/tidecoin`
- `tink-crypto/tink-cc`
- `tink-crypto/tink-go`
- `tink-crypto/tink-java`
- `tink-crypto/tink-objc`
- `tink-crypto/tink-py`
- `tiredvpn/tiredvpn`
- `tprest/falcon.py`
- `vapor/jwt-kit`
- `veil-net/conflux`
- `VirgilSecurity/virgil-crypto-c`
- `wolfSSL/osp`
- `wolfSSL/wolfcrypt-jni`
- `wolfSSL/wolfssl`
- `wolfSSL/wolfTPM`
- `Xor-el/CryptoLib4Pascal`
- `ziglang/zig`
- `zoahdev/kinegrant-protocol`

## Corpus C: commits only (11 repositories)

- `0rlych1kk4/quantum_identity_system`
- `arnaultpascual/Verrou`
- `gravity-postquantum/gravity-sphincs`
- `gravity-postquantum/prune-horst`
- `mpaymenremora/QuantumSeal`
- `open-quantum-safe/liboqs-js`
- `Quantova/QCore.js`
- `Quantova/QCore.py`
- `rasidi3112/Quantum-crypto`
- `vesvault/libVES.c`
- `XiantingWu/PQCensus`
