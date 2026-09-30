# MudMap — contexto para o Claude

Segmentação mineral **determinística** a partir de mapas EDS (MEV-EDS exportados do AZtec, um mapa por
elemento + a imagem de elétrons/BSE, alinhados e com tamanho de pixel conhecido) e o software desktop
**MudMap Studio** (PyQt6 → .exe) que revisa/edita/relata a segmentação. Amostra no repositório:
**RJS0649RJ**, sítios 1.1 e 1.2. Código MIT; dados CC BY 4.0 (`LICENSE`, `LICENSE-DADOS.md`, `CITATION.cff`).

## Runbooks = fonte de verdade (ler antes de agir)

| frente | comando | arquivo |
|---|---|---|
| pipeline (`scripts/`, `config/`, `estado/`, `sitios/`) | `/S_MudMap` | `.claude/skills/S_MudMap/SKILL.md` |
| software (`app/`, build, instalador, CI) | `/S_MudMapStudio` | `.claude/skills/S_MudMapStudio/SKILL.md` |

Cada runbook termina em **Estado / próximo passo**. Ao concluir uma etapa, atualizar essa seção.

**Estado em 2026-09-30:** sítios 1.1 e 1.2 concluídos (1.2 = sítio ativo em `estado/`; 1.1 em `sitios/1.1/`;
pacotes em `saida/mudmap/`); sítios 2–4 aguardam o USUÁRIO organizar `EDS/2..4` em subpastas — não começar
antes. App v0.5.0 (fases 1–5 feitas), aguardando o retorno do usuário.

## Princípio inegociável: classificação determinística

A atribuição de mineral a cada pixel/região sai de **código determinístico** (regras estequiométricas sobre
o vetor de frações de cátion, modelos por região ou k-means com semente fixa), nunca de julgamento "no olho"
do modelo. O papel do agente é escrever, rodar e explicar o código, e resumir evidências (ex.: "região X:
Si dominante, cátions ≈ 0 → candidata a quartzo"). Isso mantém tudo reprodutível e auditável.

## Preferências do usuário (valem sempre)

- Conversar em português. Perguntar sempre que a opinião dele contar; entregar por fases testadas.
- Nunca editar dados/config do usuário por conta própria (testes só em cópias); nunca descartar trabalho
  commitado sem confirmar; prévia antes/depois de cada etapa do pipeline (REGRAS do `/S_MudMap`).
- Tokens perto do fim: fazer só o que couber, salvar estado, registrar no SKILL.md o ponto exato de
  parada e o próximo passo, e pausar pedindo para retomar.

## Ambiente (qualquer máquina)

- **Começo de sessão:** `python scripts/diagnostico.py` — confere Python, pacotes, config × mapas, `estado/`,
  sítios e pacotes, e diz o próximo passo (código de saída 1 se houver erro).
- **Python 3.12+** num `.venv` na raiz, com as versões fixadas: `requirements.txt` (app + scripts),
  `requirements-scripts.txt` (só o pipeline, sem Qt), `requirements-dev.txt` (+ pytest e PyInstaller).
  - Claude Code **na web**: o hook `.claude/hooks/session-start.sh` cria o `.venv` e põe o `python` dele no PATH.
  - **PC do operador**: `MudMapStudio.bat` (Windows) / `./mudmap_studio.sh` criam o `.venv`; ou
    `py -3.12 -m venv .venv` (Windows) / `python3 -m venv .venv` + `pip install -r requirements.txt`.
    Nos comandos, `$py` = `.venv\Scripts\python.exe` (Windows) ou `.venv/bin/python`.
- Os runbooks citam a máquina original; aqui vale:

| nos runbooks | em outra máquina |
|---|---|
| `$py = "C:\Users\faria\...\Python312\python.exe"` | o Python do `.venv` (acima) |
| "Bash falha → usar PowerShell" | só se o Bash do Claude falhar nessa máquina |
| `C:\MudMapStudio\dist\...` + atalho na Área de Trabalho | `app\build_exe.ps1 -Saida <pasta>` ou o instalador do Release |
| links `claude.ai/artifact/...` (inspetores) | da conta do autor; regerar com `exportar_graos.py` |
| backups extras em `sitios/1.1/`, `sitios/1.2/` | só na máquina original (não estão no git) |

- Sem tela: `QT_QPA_PLATFORM=offscreen`; no Linux o PyQt6 pede `libegl1 libgl1 libxkbcommon0 libfontconfig1
  libdbus-1-3`; no Windows sem tela, `QT_QPA_FONTDIR=C:/Windows/Fonts`.

## Estrutura

```
.claude/skills/           runbooks /S_MudMap (pipeline) e /S_MudMapStudio (software)
.claude/hooks/            SessionStart do Claude Code na web (prepara o .venv)
app/mudmap_studio/        MudMap Studio: nucleo/ (sem Qt; importa scripts/common.py e segmentar.py),
                          ui/, recursos/ (ícone + config do exemplo sintético)
app/testes/               validar_nucleo.py, testar_interface.py, estresse_4096.py
app/build_exe.ps1, app/instalador/   .exe (PyInstaller) e instalador (Inno Setup)
scripts/                  pipeline por linha de comando (um script por etapa; ver /S_MudMap)
tests/                    pytest (funções do pipeline, configs reais, pacotes = estado, exemplo, sítios)
config/classificacao.yaml regras dos minerais do sítio ATIVO (ordem = prioridade; id = posição)
estado/                   sítio ativo: rotulos.npy (0 = livre, 1..N), rotulos_prev.npy, progresso.json, clusters
sitios/<s>/               sítios arquivados (estado/, classificacao_<s>.yaml, info.json)
EDS/<n>/<sítio>/          mapas do AZtec (<El> Wt% Map Data N.tif, Electron Image N.tif); EDS/2..4 fora do git
saida/                    saídas regeneráveis (fora do git), menos saida/mudmap/*.mudmap e relatorio_final_1.*
exemplo/                  projeto sintético (python scripts/gerar_exemplo.py; fora do git)
```

## Testes (rodar da raiz depois de mexer em app/ ou scripts/)

```bash
python -m pytest                                                   # segundos
python app/testes/validar_nucleo.py [projeto]                      # núcleo × pipeline, ~30 s
QT_QPA_PLATFORM=offscreen python app/testes/testar_interface.py [saida] [--raiz projeto]   # ~30 s
python app/run_studio.py --autoteste saida/mudmap/RJS0649RJ_1.1.mudmap saida/auto.png .     # como o .exe é validado
```

Todos terminam em `RESULTADO: OK` (ou pytest verde). `projeto` default = raiz (dados reais); `exemplo/` =
sintético. Os testes não alteram config/estado do projeto (trabalham em cópias). A CI
(`.github/workflows/mudmap.yml`) roda tudo isso + o fluxo dos scripts sem Qt + .exe/instalador no Windows.

## Regras de mineral e convenções

- `config/classificacao.yaml`: condições compostas (E lógico) sobre frações de cátion, ou modelos por região
  (`mapas_grupos`) + pós-filtro de `forma`. Ordem = prioridade; **id em `rotulos.npy` = posição do mineral:
  não reordenar nem remover** (minerais novos por APPEND). Limiares calibrados a partir de grãos de referência
  (`comparar.py --calibrar`), registrados em comentário no bloco do mineral (data, referência, métrica).
  Tamanhos em µm (`*_um`) viram px num único lugar (`common.resolver_escala`).
- Coordenadas **(row, col)** = (y, x), como no napari e no scipy.
- "Presente" ≈ fração de cátion `> 0.08`; "ausente/traço" ≈ `< 0.03`; a faixa intermediária fica sem classe de
  propósito (pixels mistos de borda → revisar). O e C nunca entram na fração de cátions.
- O app **reusa** as funções do pipeline: mudou a matemática num lugar, os dois mudam (`validar_nucleo.py` confere).
- Todo passo que grava `estado/rotulos.npy` salva antes `estado/rotulos_prev.npy` (regra 7 do `/S_MudMap`).
- Textos, comentários e mensagens em português; arquivos em LF (`.gitattributes`).
