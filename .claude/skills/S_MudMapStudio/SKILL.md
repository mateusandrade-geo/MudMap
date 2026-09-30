---
name: S_MudMapStudio
description: >
  Desenvolvimento do MudMap Studio — o software desktop (PyQt6 → .exe) que abre um pacote
  .mudmap por amostra e substitui o napari e o inspetor HTML: modos Inspetor, Edição,
  Segmentar e Relatório (multi-sítio). Arquitetura, formato, build, instalador, CI, testes, decisões e estado.
invocation: user
---

# S_MudMapStudio — o software (app/)

Runbook do **software**. O pipeline de segmentação (scripts/, estado/, sítios) é o `/S_MudMap`;
o app **reaproveita a matemática do pipeline** (importa `scripts/common.py` e `scripts/segmentar.py`).

## Retomar após /clear (ou numa máquina nova)

1. Ler **Estado / próximo passo** (fim deste arquivo) — inclui pendências.
2. Ambiente: ver **Comandos**; `$py scripts/diagnostico.py` confere Python, pacotes (PyQt6 incluso) e dados.
3. Conferir que nada quebrou: `$py -m pytest -q`, `$py app/testes/validar_nucleo.py` e
   `$py app/testes/testar_interface.py` (os dois últimos terminam com `RESULTADO: OK`; ~30 s cada).
4. Rodar do código: `$py app/run_studio.py [arquivo.mudmap | --exemplo]` (ou `MudMapStudio.bat` /
   `./mudmap_studio.sh`, que criam o `.venv` na 1ª vez).

## Decisões do usuário — não reabrir sem perguntar

- Python + **PyQt6** → `.exe` (PyInstaller onedir). Na máquina do autor fica **fora do OneDrive**:
  `C:\MudMapStudio\dist\MudMapStudio\MudMapStudio.exe` (atalho "MudMap Studio" na Área de Trabalho). Para os
  demais: Release do GitHub (`MudMapStudio-setup.exe` instalador ou `MudMapStudio-windows.zip` portátil).
  EDS de 1024/2048/4096 px.
- Abre **`.mudmap`** (pacote por amostra) e importa pasta do projeto (sítio ativo/arquivado ou pasta EDS);
  salva no `.mudmap` (com versões) + **Exportar p/ estado/** (backup `rotulos_prev.npy`) p/ o pipeline seguir.
- **Tema escuro**; barra de modos (Inspetor · Edição · Segmentar · Relatório = F1–F4) + camadas + canvas +
  painel do modo + status. Entrega por fases com .exe testado; **perguntar** quando a opinião dele contar.
- Relatório (2026-09-28): gráficos **QPainter nativos** (sem matplotlib; PNG 2× / SVG, fundo claro por padrão);
  painel à direita do canvas (clicar num gráfico destaca no canvas; "painel cheio" esconde o canvas); aba
  **Comparar** com lista de .mudmap (lembrada), a amostra aberta ao vivo, seletor **por campo | por sítio**
  (1.1+1.2 → sítio 1 somando áreas em µm²; campos = pontos pequenos ligados ao do sítio).
- Política do pipeline: grão = objeto ≥ area_min; menores = cimento (fora do ternário); **`matriz: true` →
  não é grão, área inteira na argila**. Nunca editar dados/config do usuário por conta própria (testes só em cópias).
- Primeira abertura sem dados: botão **"Abrir o exemplo sintético"** / `--exemplo` (2026-09-30).

## Arquitetura (`app/mudmap_studio/`, ~9 mil linhas)

`nucleo/` (sem Qt, testável; = pipeline):
- `amostra.py` — Amostra: mapas **uint8, 1 array por elemento** (nunca H×W×N float: 1 GB em 4096²), `soma`,
  `frac(i)`, máscara, rótulos, clusters, `config` (yaml resolvido em px), `regra(mid)`, `id_feldspato`
  (`feldspato: true` ou nome), `log_edicoes`, `versoes`. **`Vista`** = pilha virtual `[..., i]` p/ as funções do
  pipeline; `am.vista("frac"|"raw", exata)` (exata = float64 das regras; senão float32 do desenho);
  `elementos_da_expr('Si-Mg')`.
- `pipeline.py` — põe `scripts/` no path, reexporta `common` e `segmentar` (.exe: `--hidden-import`).
- `importar.py` — sítio ativo/arquivado/pasta EDS com os decodificadores do pipeline (mapas/máscara idênticos;
  BSE sem faixa de título; faixa "X Wt%" zerada); `_ler_pasta` + `_amostra` montam tudo; area_min por
  `common.resolver_escala(cfg, pixel_um)` (config em µm).
- `pacote.py` — formato `.mudmap`. `exportar_estado.py` — prévia/gravação em `estado/` + progresso.json.
- `exemplo.py` — projeto **sintético** determinístico (mapas no formato AZtec: matiz fixo, faixa de título,
  barra de escala, barra de info + metadados; BSE; config de `recursos/exemplo_classificacao.yaml`; rótulos de
  referência). `garantir(destino)` gera 1 vez (versão da cena em `LEIA-ME.txt`); usado pelo app, pelo
  `scripts/gerar_exemplo.py`, pelos testes e pela CI.
- `objetos.py` — grãos = componentes por mineral (ids = `exportar_graos`); composição por `bincount` canal a
  canal; `classe` Wentworth (digitize), `sub` (< area_min), `matriz` (classe = argila); Na-K-Ca.
- `render.py` — Compositor: fundo BSE/aditivo/canal + clusters + minerais (LUT objeto/fino ou por rótulo),
  blocos de 512 linhas, `passo` (prévia), `compor_regiao` (remendo); canal = `common.canal` +
  `segmentar._suave_mascarado` (cache LRU 3). `cores.py` — LUTs sem matplotlib.
- `edicao.py` — Editor: `aplicar` (proteções), pincel (cápsula), `rasterizar` (retângulo/elipse/polígono/laço),
  formas c/ filtro químico, balde, remover, pontos, morfologia vetorizada, propagar (= propagar.py), limpar fora;
  histórico de **trechos** (só pixels alterados) → desfazer ilimitado (`_mover`, `_repor`).
- `segmentacao.py` — candidato = funções do `segmentar.py` sobre `am.vista(..., True)`; comparar/calibrar =
  `comparar.py` vetorizado; k-means = `reconhecer.py`. `config_texto.py` — grava 1 mineral preservando
  comentários (passar sempre o `pixel_um` da amostra: com `pixel_um: auto` na config não há outro).
- `relatorio.py` — **= `relatorio_final.py`** a partir dos objetos (ms): frações por área, D50 por nº,
  composição = `min_frac`, Na-K-Ca por objeto; extras `classe_shepard` (1954), D50 por área, finos por mineral,
  `compacto()`, `agregar(por)` (soma µm²), `resumo_de_arquivo` (cache JSON em AppLocalData: caminho+mtime+
  tamanho+`VERSAO_CALC`), CSV pt-BR (`;`, vírgula, BOM) e JSON.
- `exportar_html.py` — inspetor HTML (`scripts/inspetor_template.html`) com os dados do `exportar_graos.py` e as
  imagens em data URI (arquivo único; > 65 535 objetos → os maiores). No .exe: `--add-data ...;scripts`.

`ui/`:
- `janela.py` — modos (tabela `MODOS`), arquivos (`abrir_arquivo`, `importar_pasta`, `abrir_exemplo`), atalhos,
  render, destaque do Relatório; `_rodar(rótulo, fn, fim)` = tarefa longa no `Servico` `self.tarefas` (barra de
  progresso, `_ocupado` trava ações).
- `dialogos.py` — `DialogoSitios` e **`Servico`**: thread persistente, 1 tarefa por vez, callbacks na thread da
  interface `pedir(fn(prog), pronto, erro(curta, detalhe), progresso, coalescer)`; detalhe "" = ValueError
  (erro de usuário). Usado por janela (fila), Segmentar (coalescente) e Comparar (fila).
- `renderizacao.py` — thread própria do render: prévia + cheia, cancelável entre blocos.
- `canvas.py` (zoom/pan, pirâmide, ferramentas, remendo, régua, escala, legenda em gradiente), `camadas.py`,
  `contraste.py`, `inspetor.py` (ficha; ternário = `graficos.TernarioFicha`), `tabela.py` (sort/filter numpy),
  `edicao.py` + `controle_edicao.py`, `segmentar.py` (painel + controle), `tema.py`, `icones.py` (SVG).
- `comum.py` — **utilitários únicos** (não duplicar): fmt, num_bonito, descartar, rolagem, **PainelRolavel**
  (base dos painéis laterais, conteúdo em `self.L`), Secao, Segmentado, Mensagem, sobreposicao, botao,
  botao_seg, botao_x, sw, mudo, icone_cor.
- `graficos.py` — QPainter: `Grafico` com `desenhar(p, w, h, pal, alvos)` PURO (tela = PAL escuro + alvos de
  mouse; PNG/SVG = PAL claro); Blocos, TernarioShepard (campos de Shepard, satélites, rótulos com fundo),
  TernarioNaKCa, TernarioFicha, HistogramaDiametros (log, clique/arraste), MapaCalor, Tabela, Imagem;
  `compor_figura`, `exportar_png`, `exportar_svg`. Paletas validadas (skill dataviz, `validate_palette.py`):
  série única = azul; sítios = slots 1–3 + forma + rótulo (> 3: só forma + rótulo); calor = rampa azul.
- `relatorio.py` — PainelRelatorio (abas Amostra | Comparar em `_Grade` 1↔2 colunas) e ControleRelatorio
  (calcula, destaca: camada "rel", objeto na "A"; exporta — CSV de grãos e HTML via `_rodar`; comparação:
  QSettings `comparar/arquivos`, `comparar/por`).

Padrões: Edição/Segmentar desenham **por rótulo**; `editor.versao` marca mudança → grãos recalculados ao voltar
ao Inspetor ou ao Relatório (`_objetos_novos` → `rel.entrar()`); resultados com versão velha são descartados;
edição local remenda só a região. No Relatório a barra de ferramentas do meio fica `Ignored` na horizontal
(senão a barra larga da Edição espreme o painel).

Fora do pacote: `app/run_studio.py` (entrada do .exe), `build_exe.ps1`, `versao_exe.py` (Propriedades do .exe
a partir de `__version__`), `gerar_icone.py`, `instalador/MudMapStudio.iss` (Inno Setup), `testes/`.

## Formato `.mudmap` (ZIP)

`manifest.json` (amostra, sítio, pixel_um, shape, elementos, minerais {id,nome,cor}, area_min, origem,
`versoes`, `edicoes`) · `config.yaml` · `mapas/<El>.png` (uint8) · `bse.png` · `mascara.png` · `rotulos.npy` ·
`clusters.npy/.json` (opcional) · `historico/rotulos_<data>.npy` (5 últimas). Gerar do projeto:
`$py scripts/exportar_mudmap.py [--sitio 1.1 | --todos]` → `saida/mudmap/` (versionado no git).

## Comandos

- **`$py`** = Python 3.12 do ambiente: `.venv\Scripts\python.exe` (Windows) · `.venv/bin/python` (Linux/macOS);
  criar: `py -3.12 -m venv .venv` / `python3 -m venv .venv` + `$py -m pip install -r requirements.txt`
  (+ `requirements-dev.txt` p/ pytest). Na máquina do autor: `C:\Users\faria\AppData\Local\Programs\Python\
  Python312\python.exe` (o `python` do PATH é o alias da Store) e **Bash falha → PowerShell**.
- **Build** (Windows): `powershell -ExecutionPolicy Bypass -File app\build_exe.ps1 [-Python <py>] [-Saida
  C:\MudMapStudio] [-Dist dist_nova] [-Zip]` (~370 MB, ~2,5 min; instala o PyInstaller se faltar).
  **Com o app aberto a pasta `dist` fica travada** (o PyInstaller chega a apagar parte dela antes de falhar!):
  confira `Get-Process MudMapStudio`; se aberto, gere em `-Dist dist_nova`, teste e troque as pastas depois
  que o usuário fechar (nunca fechar o app dele).
- **Instalador**: `iscc /DVersao=<x.y.z> /DOrigem=<pasta dist\MudMapStudio> /O<saida> app\instalador\MudMapStudio.iss`
  → `MudMapStudio-setup.exe` (por usuário, sem admin; Menu Iniciar, atalho opcional, `.mudmap` → Studio).
- **Autoteste do .exe** (sem tela): `$env:QT_QPA_PLATFORM="offscreen"; $env:QT_QPA_FONTDIR="C:/Windows/Fonts"`;
  `MudMapStudio.exe --autoteste <saida\mudmap\RJS0649RJ_1.1.mudmap> <saida.png> <raiz_projeto>` →
  `<saida.png>.log` "RESULTADO: OK" (abre, canal, edição + desfazer, segmentar, k-means, config, relatório +
  6 exportações + comparação por sítio, exemplo sintético, importar). O 1.1 tem Na/feldspato; o ativo (1.2) não.
- **Testes**: `pytest` (`tests/`: funções do pipeline, exemplo, sítios, diagnóstico; segundos),
  `validar_nucleo.py [projeto]` (núcleo × pipeline, asserts; seção 7 = relatório × `relatorio_final.py`),
  `testar_interface.py [saida] [--raiz projeto]` (todos os modos, offscreen, cópias temporárias),
  `estresse_4096.py [projeto]` (tempos). `projeto` = raiz (dados reais) ou `exemplo/` (sintético).
- Sem linter instalado: checar imports não usados / nomes indefinidos com um script `ast` (não instalar nada).

## CI e Release (`.github/workflows/mudmap.yml`)

A cada push/PR: pytest + testes com os dados reais e com o exemplo (Linux, Python 3.12 e 3.13), fluxo dos scripts
**só com `requirements-scripts.txt`** (sem Qt, como o Claude conduz), troca de sítio, guarda de tamanho (> 50 MB
falha), `.exe` + instalador gerados e validados com `--autoteste` (inclusive o instalado), `MudMap-skill.zip`.
**Release**: tag `vX.Y.Z` = `__version__` (a CI confere) **ou** Actions → MudMap → Run workflow com `versao`
preenchida (cria a tag). Assets: instalador, zip portátil, skill e os `.mudmap`. Assinatura com `signtool` quando
os secrets `WINDOWS_CERT_PFX_BASE64`/`WINDOWS_CERT_SENHA` existirem (ver README).

## Armadilhas já resolvidas (não repetir)

- QSS não aceita `#RRGGBBAA` (Qt lê ARGB) → `rgba()`. `numpy.bool/float` em API Qt → converter.
- Offscreen sem fontes → `QT_QPA_FONTDIR` (Windows; no Linux o fontconfig resolve). PyInstaller com
  `--specpath` exige caminhos ABSOLUTOS. Linux sem tela: `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3`.
- Laços por objeto do pipeline são O(n·H·W) → versões vetorizadas no app (convexo só ≥ area_min).
- `segmentar.limpar` preenche buracos com pixels de outros minerais → IoU < 1 esperado (commit exclui).
- `return` dentro de `finally` engole exceções. Python inline no PowerShell quebra com aspas → usar arquivo.
- skimage 0.26: FutureWarning (`binary_opening`, `min_size`) — funciona.
- QGridLayout com alinhamento no addWidget não estica o widget → sem alinhamento + `addStretch` no cartão.
- numpy 2: `256 * uint8` estoura → `.astype(int)`. Sem Node: validador de paleta em Python.
- Widgets montados antes dos controladores: conectar com lambda tardio (`getattr(self.controle, ...)`).
- Arquivos em **LF** (`.gitattributes`: `eol=lf`; só `.ps1`/`.bat`/`.iss` em CRLF): `.Replace("...\n")` no
  PowerShell falha em CRLF.
- TIFF do AZtec é LZW: ler com **Pillow** (o `tifffile`/`imageio` exigiriam `imagecodecs`).
- Windows PowerShell 5.1 + `$ErrorActionPreference="Stop"`: redirecionar stderr de comando nativo (`2>`, `*>`)
  vira erro → não redirecionar (ver `build_exe.ps1`).
- k-means só é bit a bit idêntico entre máquinas com as mesmas versões (`requirements.txt` fixado); o
  `clusters.npy` salvo precisa ser da config atual (o do 1.1 foi recalculado em 2026-09-30).

## Números de referência

Núcleo = pipeline: máscara/mapas idênticos; canais erro rel. ~1e-7; objetos = `exportar_graos` (19.470 no 1.2);
candidatos do 1.2 × rotulado: IoU 1,000 quartzo/sulfato/clorita, 0,974 biotita, óxidos Ti 0,19 / Fe 0 (esperado);
k-means = `estado/clusters.npy` (0 px). Relatório 1.2: 15 grãos, argila 100 %, D50 1,597 µm, biotita matriz.
1.1 **depois da edição do usuário (2026-09-28 15:23, quartzo re-segmentado no app + exportado p/ estado/)**:
6.840 objetos, 95 grãos, silte 19,8 / argila 80,2 %, Shepard "argila" (antes: 6.833 · 91 · 20,4/79,6).
4096²: grãos 6 s, prévia 0,2–0,3 s, cheia 1–3 s, propagar 13 s, salvar 3 s, abrir 0,8 s, relatório ~0 s,
destaque 0,06 s, CSV de grãos 4 s e dados do HTML 2,7 s (em thread). Exemplo sintético: 640², 259 objetos, ~1 s.

## Estado / próximo passo (2026-09-30) — v0.5.0 publicável

- **Fases 1–5 feitas** (todas as planejadas): Inspetor · camadas · Edição (substitui o napari) · Segmentar ·
  **Relatório** (resumo, Shepard com campos, Na-K-Ca, diâmetros, composição, tabela, destaques no canvas,
  exportações PNG/SVG/JSON/CSV/HTML, aba Comparar por campo | sítio).
- **Repositório GitHub (2026-09-29/30)**: exemplo sintético; build sem caminho fixo + Propriedades do .exe;
  instalador; CI (Linux + Windows, .exe e instalador validados com `--autoteste`); Release por tag ou manual;
  licenças MIT (código) + CC BY 4.0 (dados); `CITATION.cff`.
- **▶ PRÓXIMO: retorno do usuário** sobre o Relatório/app. Ideias só se ele pedir: vários .mudmap em abas;
  D50 por área como padrão; nomes dos campos de Shepard na figura exportada; excluir aiohttp/certifi do .exe;
  assinatura do .exe (certificado). Sítios 2–4 aguardam o usuário organizar `EDS/2..4` (runbook /S_MudMap).
