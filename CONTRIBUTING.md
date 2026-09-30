# Guia do mantenedor

Como mudar o MudMap sem quebrar o que outro operador baixa e roda.

## Fluxo de mudanças

1. Trabalhe numa **branch** (ou peça ao Claude: ele cria a branch, testa e abre o PR).
2. Rode localmente o que a mudança toca: `python scripts/diagnostico.py`, `python -m pytest` e, se mexeu em
   `app/` ou `scripts/`, `python app/testes/validar_nucleo.py` e `app/testes/testar_interface.py`
   (ver `CLAUDE.md`).
3. Abra um **pull request** para a `main`. A CI roda: pytest, dados reais, exemplo sintético, fluxo dos
   scripts sem Qt, `.exe` e instalador no Windows. Só faça o merge com tudo verde.
4. Atualize o **Estado atual / próximo passo** do runbook que você usou (`/S_MudMap` ou `/S_MudMapStudio`).

Evite enviar arquivos direto na `main` pelo site ("Add files via upload"): o envio pula a CI e os arquivos
caem na raiz, fora da estrutura. Se precisar enviar pelo site, envie para uma branch e abra o PR.

## Proteger a `main` (uma vez, no GitHub)

**Settings → Rules → Rulesets → New branch ruleset**:

- *Target branches*: `main` (Include default branch);
- marque **Require a pull request before merging**;
- marque **Require status checks to pass** e adicione os checks do workflow `MudMap`:
  `Versão e tamanho dos arquivos`, `Testes · Linux · Python 3.12`, `Testes · Linux · Python 3.13`,
  `Fluxo do Claude · só scripts, sem Qt`, `Executável e instalador Windows`, `Pacote da skill do Claude (claude.ai)`;
- marque **Block force pushes**; em *Bypass list*, só os administradores (para emergências).

## Publicar uma versão

1. Suba a versão em `app/mudmap_studio/__init__.py` (`__version__`) e em `CITATION.cff` (`version`), e
   registre o que mudou no `/S_MudMapStudio` (Estado). Merge na `main`.
2. **Actions → MudMap → Run workflow**, branch `main`, campo *versao* = a mesma versão (ex.: `0.5.1`).
   Alternativa: criar a tag `v0.5.1` (Releases → *Draft a new release* → *Choose a tag*).
3. A CI confere que a versão pedida = `__version__`, roda todos os testes e publica o Release com
   `MudMapStudio-setup.exe`, `MudMapStudio-windows.zip`, `MudMap-skill.zip` e os `.mudmap`.

## Assinatura do executável

O aviso do Windows SmartScreen só some com o `.exe` e o instalador **assinados** por um certificado de
assinatura de código (e, com certificados comuns, depois de os arquivos ganharem reputação com os downloads).
A CI já assina sozinha quando o certificado estiver cadastrado:

1. Obter um certificado de assinatura de código (`.pfx` + senha). Caminhos comuns:
   [SignPath Foundation](https://signpath.org) (gratuito para projetos de código aberto com licença aprovada
   pela OSI — o MudMap é MIT), [Azure Trusted Signing](https://learn.microsoft.com/azure/trusted-signing/)
   (assinatura mensal) ou um certificado OV/EV comprado de uma autoridade certificadora.
2. Em **Settings → Secrets and variables → Actions**, criar `WINDOWS_CERT_PFX_BASE64` (o `.pfx` em base64:
   `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))` no PowerShell) e `WINDOWS_CERT_SENHA`.
3. Rodar a CI de novo: os passos "Assinar o executável" e "Assinar o instalador" usam o `signtool` com carimbo
   de tempo. SignPath e Azure usam ações próprias em vez do `.pfx` — nesse caso troque esses passos pela ação
   do serviço escolhido.

## Dados e tamanho do repositório

- Hoje ~70 MB. A CI falha se algum arquivo versionado passar de **50 MB** (o GitHub recusa > 100 MB).
- **Git LFS não é usado de propósito**: o "Download ZIP" do GitHub e os clones sem LFS receberiam só
  ponteiros no lugar dos TIFFs, e a cota gratuita de banda do LFS acabaria rápido com a CI. Se um dia os
  dados passarem de ~1 GB, prefira publicar cada conjunto de sítios como anexo de Release (ou Zenodo, com DOI)
  e baixá-los por um script.
- `EDS/2..4` (1,1 GB, ainda não organizados) estão no `.gitignore`. Ao organizar um sítio em
  `EDS/<n>/<n.k>/`, versione só os `.tif` necessários (elementos da config + Electron Image) e confira o
  tamanho com `python scripts/diagnostico.py`.
- Novos dados entram sob **CC BY 4.0** (ver `LICENSE-DADOS.md`); se não puderem ser públicos, não os
  versione neste repositório.

## Claude Code na web

O `.claude/settings.json` registra o hook `SessionStart` (`.claude/hooks/session-start.sh`). Ele só age no
Claude Code na web (`CLAUDE_CODE_REMOTE=true`): cria `.venv/` com Python 3.12+ e as versões fixadas, instala as
bibliotecas do Qt sem tela e põe o `python` do `.venv` no PATH da sessão. No PC do operador o hook sai sem fazer
nada. Se numa máquina Windows sem Bash ele gerar aviso ao abrir a sessão, desligue-o só para você em
`.claude/settings.local.json` (`{"hooks": {}}`).
