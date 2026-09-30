# MudMap

O MudMap é um software destinado ao mapeamento e à classificação mineralógica de imagens obtidas por microscopia eletrônica de varredura (MEV), com foco na caracterização de rochas sedimentares analisadas em lâminas petrográficas.

O software permitirá a identificação e classificação dos minerais presentes nas amostras a partir da integração de diferentes mapas elementares obtidos por espectroscopia de raios X por dispersão de energia (EDS). Como as lâminas petrográficas são confeccionadas com resina epóxi, o sistema também contará com uma etapa de correção dos teores de carbono e oxigênio associados à resina, de modo a minimizar sua influência na classificação mineralógica.

A classificação dos minerais será realizada por meio de técnicas de aprendizado de máquina, considerando tanto as composições químicas teóricas e características de cada mineral, quanto dados reais provenientes de um banco de dados de referência. Dessa forma, o MudMap será capaz de integrar os dados elementares obtidos por EDS e, a partir das assinaturas químicas identificadas, atribuir classes mineralógicas aos diferentes pixels ou regiões da imagem.

O objetivo é desenvolver, portanto, uma ferramenta capaz de automatizar e tornar mais consistente o processo de interpretação mineralógica de imagens de MEV-EDS, permitindo a geração de mapas mineralógicos quantitativos e a caracterização da distribuição espacial dos minerais em rochas sedimentares.

![MudMap Studio — modo Inspetor, amostra RJS0649RJ sítio 1.2](docs/studio_inspetor.jpg)

## O que tem aqui

- **MudMap Studio** (`app/`): aplicativo de desktop para inspecionar, editar, segmentar e gerar o
  relatório de uma amostra. Modos **Inspetor** (clique num grão → área, diâmetro, composição),
  **Edição** (pincel, borracha, balde, polígono, laço, pontos → regiões, propagar, desfazer),
  **Segmentar** (candidato pelas regras da config, comparação IoU/Dice, calibração, k-means) e
  **Relatório** (Shepard, D50, composição por mineral, ternário Na-K-Ca de feldspatos; PNG/SVG/CSV/JSON/HTML).
- **Pipeline por linha de comando** (`scripts/`): as mesmas etapas em scripts determinísticos, conduzidos
  pelo **Claude** numa conversa com os runbooks `/S_MudMap` (pipeline) e `/S_MudMapStudio` (software).
- **Dados reais** (CC BY 4.0): amostra RJS0649RJ, sítios 1.1 e 1.2 — mapas EDS do AZtec (`EDS/`),
  segmentação (`estado/`, `sitios/`), regras calibradas (`config/`), pacotes prontos
  (`saida/mudmap/*.mudmap`) e relatórios finais (`saida/relatorio_final_1.*`).
- **Exemplo sintético**: um projeto completo gerado por código, para testar tudo sem dados reais.

## Como baixar e usar

### 1. Só o aplicativo (Windows, sem instalar Python)

Na página de [Releases](https://github.com/mateusandrade-geo/MudMap/releases/latest):

- **`MudMapStudio-setup.exe`** — instalador: não pede administrador, cria o atalho no Menu Iniciar e faz o
  duplo clique em arquivos `.mudmap` abrir o app; **ou**
- **`MudMapStudio-windows.zip`** — portátil: extraia e rode `MudMapStudio\MudMapStudio.exe`.

Na tela inicial: **"Primeira vez? Abrir o exemplo sintético"**, ou **Abrir .mudmap** com um dos pacotes
reais (`RJS0649RJ_1.1.mudmap`, `RJS0649RJ_1.2.mudmap`, também no Release), ou **Importar pasta do projeto**
apontando para a pasta deste repositório (lê os mapas do AZtec direto).

> Enquanto o executável não for assinado digitalmente (ver [Assinatura](CONTRIBUTING.md#assinatura-do-executável)),
> o Windows pode avisar "O Windows protegeu o computador": clique em **Mais informações → Executar assim mesmo**.

### 2. Pelo código-fonte (Windows, Linux ou macOS)

Precisa do [Python 3.12 ou mais novo](https://www.python.org/downloads/) (no Windows, marque *Add python.exe to PATH*).

1. Baixe o repositório: botão **Code → Download ZIP** (ou `git clone https://github.com/mateusandrade-geo/MudMap.git`).
2. Abra o app:
   - **Windows:** duplo clique em **`MudMapStudio.bat`** (ou arraste um `.mudmap` para cima dele)
   - **Linux/macOS:** `./mudmap_studio.sh` (ou `./mudmap_studio.sh --exemplo`)

   Na primeira vez ele cria o ambiente `.venv` e instala as dependências (alguns minutos, precisa de internet).

Manualmente, se preferir:

```bash
python -m venv .venv                       # Windows: py -3.12 -m venv .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -r requirements.txt            # versões exatas testadas (só os scripts: requirements-scripts.txt)
python scripts/diagnostico.py              # confere ambiente e dados e diz o próximo passo
python app/run_studio.py                   # ou: python app/run_studio.py saida/mudmap/RJS0649RJ_1.1.mudmap
```

### 3. Com o Claude

O fluxo de segmentação foi feito para ser conduzido pelo Claude: ele roda os scripts, mostra as prévias,
resume os números e só grava o que você aprovar. Dois runbooks (skills) guardam as regras, as decisões e o
estado de cada frente:

| comando | para quê | arquivo |
|---|---|---|
| `/S_MudMap` | segmentar/revisar/calibrar/relatar uma amostra (pipeline) | [`.claude/skills/S_MudMap/SKILL.md`](.claude/skills/S_MudMap/SKILL.md) |
| `/S_MudMapStudio` | desenvolver o app, gerar .exe/instalador, CI | [`.claude/skills/S_MudMapStudio/SKILL.md`](.claude/skills/S_MudMapStudio/SKILL.md) |

- **Claude Code no seu PC:** baixe o repositório, abra o Claude Code na pasta e peça, por exemplo,
  *"rode o diagnóstico e continue o /S_MudMap"*. O `CLAUDE.md` e as skills são carregados sozinhos.
- **Claude Code na web:** o hook `.claude/hooks/session-start.sh` prepara o Python 3.12 e as dependências
  quando a sessão abre.
- **claude.ai (com execução de código ligada):** envie o **`MudMap-skill.zip`** do
  [Release](https://github.com/mateusandrade-geo/MudMap/releases/latest) como skill
  (Configurações → Capacidades → Skills) e anexe os mapas EDS na conversa. Dá para baixar só o
  [runbook do pipeline](https://raw.githubusercontent.com/mateusandrade-geo/MudMap/main/.claude/skills/S_MudMap/SKILL.md),
  mas ele precisa do código deste repositório ao lado.

## Dados e projeto

```
config/classificacao.yaml   regras dos minerais do sítio ATIVO (ordem = prioridade)
estado/                     segmentação do sítio ativo: rotulos.npy (0 = livre, 1..N = mineral),
                            progresso.json, clusters.npy/.json, rotulos_prev.npy (desfazer)
sitios/<s>/                 sítios arquivados (estado + config + info.json)
EDS/1/1.1, EDS/1/1.2        mapas do AZtec: "<El> Wt% Map Data N.tif" + "Electron Image N.tif"
saida/mudmap/*.mudmap       um pacote por sítio (abre direto no app; regravado pelo exportar_mudmap.py)
saida/relatorio_final_1.*   relatórios finais dos sítios 1.1 e 1.2 (PNG + JSON)
```

- Ver/trocar o sítio ativo: `python scripts/ativar_sitio.py --listar` e `python scripts/ativar_sitio.py 1.1`.
- Dados novos: coloque os TIFFs exportados do AZtec (um por elemento + a Electron Image) em
  `EDS/<amostra>/<sítio>/` e siga "Trocar de sítio" no `/S_MudMap`. O tamanho do pixel é lido dos
  metadados do TIFF (`pixel_um: auto`). Os mapas dos sítios 2–4 (1,1 GB) ainda não estão no repositório.
- Exemplo sintético: `python scripts/gerar_exemplo.py` cria `exemplo/` (projeto separado; rode os
  scripts de dentro dele, `python ../scripts/reconhecer.py`).

## Pipeline por linha de comando

Rode na raiz do projeto. Passo a passo, regras e decisões no [`/S_MudMap`](.claude/skills/S_MudMap/SKILL.md).

| Etapa | Script |
|---|---|
| Conferir ambiente e dados | `diagnostico.py` |
| Reconhecimento (k-means, sem commitar) | `reconhecer.py`, `candidatos.py` |
| Segmentar um mineral por vez | `segmentar.py --mineral <m> --previa` / `--auto` |
| Revisar | `revisar_commit.py`, `remover_objeto.py`, `revisar_pontos.py`, `propagar.py`, `mapa_atual.py` |
| Calibrar a regra | `comparar.py --mineral <m> --calibrar` |
| Resultados | `exportar_graos.py` (inspetor HTML), `relatorio_final.py --previa`, `exportar_mudmap.py` |
| Sítios | `arquivar_sitio.py`, `ativar_sitio.py` |
| Editores napari (opcionais) | `segmentar.py` sem `--auto`, `editor_completo.py`, `propagar.py`, `revisar_regioes.py`, `ancorar_centros_bse.py` — `pip install -r requirements-napari.txt` |

A classificação é **determinística**: regras estequiométricas sobre frações de cátion (sem O e C),
modelos por região e k-means com semente fixa — o mesmo dado, com as mesmas versões
(`requirements.txt`), gera sempre o mesmo resultado.

![Relatório do sítio 1.1 no MudMap Studio](docs/relatorio_RJS0649RJ_1.1.png)

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest                                            # funções do pipeline, configs, pacotes, exemplo
python app/testes/validar_nucleo.py                         # núcleo do app × scripts (dados reais)
QT_QPA_PLATFORM=offscreen python app/testes/testar_interface.py saida/testes_ui   # interface, sem tela
python app/run_studio.py --autoteste saida/mudmap/RJS0649RJ_1.1.mudmap saida/auto.png .
```

A cada push o GitHub Actions ([`.github/workflows/mudmap.yml`](.github/workflows/mudmap.yml)) roda tudo isso
com os dados reais e com o exemplo, o fluxo dos scripts sem Qt (como o Claude conduz) e gera e valida o `.exe`
e o instalador no Windows. Como publicar uma versão, proteger a `main`, assinar o `.exe` e lidar com dados
grandes: [CONTRIBUTING.md](CONTRIBUTING.md).

## Licença e citação

- **Código** (app, scripts, skills, testes, workflow): [MIT](LICENSE).
- **Dados** da amostra RJS0649RJ (EDS, rótulos, pacotes, relatórios, figuras): [CC BY 4.0](LICENSE-DADOS.md).
- Para citar: [`CITATION.cff`](CITATION.cff) (botão *Cite this repository* no GitHub) — Mateus Andrade e
  Lorran Faria do Nascimento.
