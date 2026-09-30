---
name: S_MudMap
description: >
  Segmenta minerais a partir de mapas EDS (um mapa por elemento, AZtec), de forma
  determinística e por partes (um mineral por vez, estado em disco), com revisão
  humana (MudMap Studio, napari ou imagem de pontos), propagação por exemplo, remoção
  de objetos, calibração de regras, relatório granulométrico e prévias no chat a cada etapa.
invocation: user
---

# S_MudMap — segmentação mineral por EDS (pipeline)

Runbook do **pipeline** (scripts/, config, estado/, sítios). O código está em `scripts/`; o `estado/`
em disco é a verdade. O **software** (app desktop que substitui napari + inspetor) tem runbook próprio:
**`/S_MudMapStudio`** (`app/`).

## Retomar após /clear (ou numa máquina nova)

1. `$py scripts/diagnostico.py` → confere Python, pacotes, projeto, sítio ativo, mapas e `estado/`, e
   diz o próximo passo. Se apontar FALTA/ERRO, resolver antes (ver **Ambiente**).
2. Ler **Estado atual** (abaixo) e seguir o **▶ PRÓXIMO PASSO**.
3. `$py scripts/mapa_atual.py` → `saida/previa_atual.png` (minerais commitados do sítio ativo).
4. `estado/` = **sítio ativo** (`config['sitio']`); sítios concluídos ficam em `sitios/<s>/` (ver Multi-sítio).

## Ambiente (qualquer máquina)

- **Python 3.12** (testado; 3.11 e 3.13 também servem). Uma vez, na raiz do projeto:
  `py -3.12 -m venv .venv` (Windows) ou `python3 -m venv .venv` (Linux/macOS), e depois
  `$py -m pip install -r requirements.txt` (versões exatas testadas; só os scripts, sem o app:
  `requirements-scripts.txt`). O `MudMapStudio.bat` / `mudmap_studio.sh` criam o mesmo `.venv`.
- **`$py`** nos comandos = Python do ambiente: `.venv\Scripts\python.exe` (Windows) ou
  `.venv/bin/python` (Linux/macOS). Rodar SEMPRE da raiz do projeto (caminhos relativos a `config/`,
  `estado/`, `saida/`); `PYTHONPATH` não é necessário.
- **Windows**: se o Bash do Claude falhar (fork), usar PowerShell: `& $py scripts\x.py`. Python inline com
  aspas quebra no PowerShell → escrever um .py. Caminhos com espaço (`"EDS/1/1.2/Electron Image 2.tif"`)
  entre aspas. O `python` do PATH pode ser o alias da Microsoft Store → usar o `py` ou o `.venv`.
- **Sem tela** (Claude na nuvem, claude.ai, servidor): só os caminhos sem janela (`--previa`, `--auto`,
  `revisar_*` por imagem, `comparar`, relatórios). MudMap Studio e napari exigem tela.
- **claude.ai** (skill enviada como `.zip`): copiar a pasta da skill para um diretório gravável e usá-la
  como raiz; os mapas do AZtec vêm anexados na conversa (ver "Trocar de sítio").
- napari (legado, `requirements-napari.txt`): janela na tela do usuário, sempre em background; commit ao
  FECHAR (matar = cancela).
- **Treinar sem dados reais**: `$py scripts/gerar_exemplo.py --sem-rotulos` → projeto sintético em
  `exemplo/`; rodar os scripts de DENTRO dele (`cd exemplo; $py ../scripts/reconhecer.py`).

## Dados e config

- Mapas AZtec coloridos em `EDS/<n>/<sítio>/` (um `.tif` por elemento; `Electron Image N.tif` = BSE).
  `common.py` decodifica brilho→intensidade, recorta a barra de info, mascara o overlay branco e exclui
  a faixa de título do topo (dimensões intactas → `rotulos.npy` alinhado).
- `config/classificacao.yaml`: `amostra`, `elementos`, `sitio`, `pasta_dados`, `bse`, `pixel_um` (`auto` =
  `<PixelWidth_um>` da tag TIFF 270; valor explícito é conferido contra o TIFF → erro se ≠ 1%), `d_min_um`,
  e por mineral: `fonte_default`, `condicoes`, `mapas_seg`/`mapas_modo`/`mapas_limiar`/`mapas_q`,
  `disseminado`, `mapas_grupos`/`suavizar_um`, `forma`, `matriz`, `feldspato`, `cor`. ORDEM = prioridade.
- **Tamanhos em µm**: `d_min_um` (diâmetro equivalente do menor grão, mesma métrica do Wentworth),
  `suavizar_um`, `forma {close_um, d_min_um}` → px num ponto só (`common.resolver_escala`, chamado por
  `carregar_config` e pelo app). Valores = calibração do 1.1 (lá reproduzem exatamente os px antigos:
  area_min 30, r 15/21/27, close 1/3, forma 30/500). Pisos 4 px (área) / 1 px (raio) com aviso `[escala]`.
  Chaves só em px continuam valendo (configs arquivadas antigas).
- **`matriz: true`** (por mineral, NA CONFIG DE CADA SÍTIO): matriz contínua não é grão → o relatório soma
  a área inteira na argila; inspetor marca `cl: "matriz"`. Decidir por sítio (1.1: biotita+clorita; 1.2:
  só biotita — lá a clorita são corpos discretos ≤ 3,4 µm).
- `mascara_amostra` com **resgate** Si/Fe/Ti (quartzo, óxidos de Fe/Ti têm soma de cátions baixa).

## Estado em disco (`estado/`)

`rotulos.npy` (id do mineral por pixel; id = posição no config) · `rotulos_prev.npy` (backup de 1 passo,
gravado antes de TODA escrita em `rotulos.npy`: `segmentar`, `revisar_commit`, `revisar_pontos --commit`,
`remover_objeto --aplicar`, `propagar`, editores napari e o "Exportar p/ estado/" do Studio) ·
`rotulos_pre_*.npy` (backups nomeados antes de lotes) · `seg_seed_<m>.npy` (sementes) ·
`clusters.npy/.json` (k-means) · `progresso.json` · `candidatos.json`.

## Multi-sítio

Só há UM `estado/` (do sítio ativo); começar outro sítio o SOBRESCREVE.
- **Ver sítios:** `$py scripts/ativar_sitio.py --listar` (situação, rótulos, se os mapas existem).
- **Concluir um sítio:** marcar `matriz` na config → `relatorio_final.py --previa --saida
  saida/relatorio_final_<s>.png` (+ `.json` ao lado) → `arquivar_sitio.py --url <artefato>` (regenera prévia +
  `exportar_graos`, grava `saida/previas_finais/previa_<s>.png`, `saida/inspetores/<s>/`,
  `sitios/<s>/estado/`, `sitios/<s>/classificacao_<s>.yaml`, `sitios/<s>/info.json`) → publicar
  `saida/inspetores/<s>/index.html` (+ `graos_bse.png`, `graos_idmap.png`) no artefato → `exportar_mudmap.py`
  (pacote p/ o app em `saida/mudmap/`, versionado no git).
- **Regenerar um sítio ARQUIVADO sem trocar `estado/`:** `mapa_atual.py`/`exportar_graos.py`/
  `relatorio_final.py --config sitios/<s>/classificacao_<s>.yaml --estado sitios/<s>/estado`
  (`exportar_graos` escreve em `saida/graos/` → copiar p/ `saida/inspetores/<s>/`).
- **Trocar de sítio (PERGUNTAR antes):** arquivar o atual → editar `sitio`/`pasta_dados`/`bse`,
  `pixel_um: auto` (+ `elementos` se faltar mapa) → limpar `estado/` (`rotulos*`, `seg_*`, `clusters*`,
  `*.json`) → `reconhecer.py`. Conferir antes: Na real? (no 1.2 o `Na.tif` era cópia do 1.1).
- **Voltar a um sítio arquivado:** `$py scripts/ativar_sitio.py <s>` (guarda o ativo em `sitios/<ativo>/`
  e restaura `sitios/<s>/estado/*` + `classificacao_<s>.yaml`; nada é apagado).

## Fluxo

0. `diagnostico.py` (ambiente e dados OK) → 1. `reconhecer.py` (k-means k=9) → 2. `candidatos.py` + prévia
**no chat**; usuário escolhe **um** mineral e o **método** → 3. PRÉ: `segmentar.py --mineral <m> --previa` →
4. commit por regra/mapa (`segmentar.py --auto`, ou `--auto --substituir` p/ RE-segmentar) **ou** edição
(MudMap Studio modos Edição/Segmentar + "Exportar p/ estado/"; ou napari/`revisar_pontos.py`) → PÓS no chat →
5. `comparar.py` (IoU/Dice + overlay) e calibrar → 6. `mapa_atual.py`; no fim `relatorio_final.py`.
**Receita de calibração:** desenho do operador × candidato → diagnosticar (máscara? bruto × fração?
co-ocorrência por pixel?) → fonte/limiar que reproduz os grãos → re-segmentar (se pedir) com backup → PÓS + IoU.
Calibração aceita = gravar na config só o bloco do mineral, preservando comentários, com data, referência e
métrica no comentário (como os blocos existentes) — só com o OK do usuário.

## Scripts (`scripts/`)

- `diagnostico.py` — checagem do ambiente/projeto/sítio ativo (`--projeto <pasta>`; código de saída ≠ 0 se
  houver erro). `ativar_sitio.py` — `--listar` / `<s>`. `gerar_exemplo.py` — projeto sintético (`exemplo/`).
- `common.py` — config (`carregar_config`, `resolver_escala`, `para_um`, `pixel_um_tiff`), decodificação,
  fração de cátions, `mascara_amostra`, `canal()` (A, A-B, A+B, A/B), regras.
- `reconhecer.py` — k-means (sklearn, random_state=0) + filtro de maioria → `clusters.*`, nomes pela 1ª regra.
- `candidatos.py` — candidatos por cluster e por mapa + prévia.
- `segmentar.py` — `--fonte {regra,mapa,cluster}` (default `fonte_default`), `--previa`, `--auto`,
  `--substituir`, `--grupo`, `--limiar/--q-mapa`. Candidato só em pixels livres (+ os do próprio mineral com
  `--substituir`); `disseminado` pula `area_min`; com `forma` a limpeza genérica é pulada; limpeza e forma
  terminam `& livre` (o `remove_small_holes` preenchia buracos com pixels FORA da amostra). `mapas_grupos` =
  UNIÃO de grupos; grupo = E de `{canal, tipo raw|frac, op, q|v}` sobre mapas **suavizados (média
  mascarada)**; `v` = limiar absoluto (estável entre sítios). `forma`: `close`, `area_min`, `ecc_min`,
  `convex`, `maior`, `preencher` (em µm: `close_um`, `d_min_um`).
- `comparar.py` — operador × candidato (IoU/Dice/prec/recall, por grão, overlay); `--calibrar` propõe regra
  (`saida/calibra_<m>.json`).
- `propagar.py` — por exemplo: núcleo erodido, semente limpa, Mahalanobis p98×thr, portão por região
  (moderado: `--gate-q 0.10 --thr 1.2 --erode 2`); `--previa` sem janela. `revisar_pontos.py` — segmentação de
  imagem com pontos azuis `#0078D7` (`--modo angular --eps-px 35`; `--modo semente` = 1 ponto por grão
  redondo; `--commit` grava). `remover_objeto.py` — objeto marcado `#3F48CC` (`--aplicar` grava).
  `revisar_commit.py --mineral <m>` — grãos numerados; `--remover "3 7 9"` zera esses grãos.
- napari (legado): `editor_completo.py`, `revisar_regioes.py` (polígono/laço do napari são bugados),
  `segmentar.py` sem `--auto/--previa`, `ancorar_centros_bse.py` (centros dos grãos na BSE → `saida/centros_bse.*`).
- `mapa_atual.py` (`--base`, `--apenas`, `--excluir`, `--saida`, `--config`, `--estado`) ·
  `relatorio_final.py --previa [--saida --config --estado]` (painel 3×3 + JSON c/ `matriz_na_argila` e
  `resolucao {d_min_um, argila_medida}`; sempre `saida/relatorio_final.json` e, com `--saida` próprio, o JSON
  ao lado do PNG) · `exportar_graos.py [--config --estado]` (inspetor HTML, template
  `inspetor_template.html`) · `arquivar_sitio.py --url` · `exportar_mudmap.py [--sitio s | --todos]`.
- `relatorio_final.py`/`exportar_graos.py` pulam o ternário Na-K-Ca se Na não estiver em `elementos`.

## REGRAS (do usuário — obrigatórias)

1. **Prévia no chat**: PRÉ antes de editar/processar, PÓS depois de commitar.
2. **Sempre perguntar** antes de: propagar, commitar, sobrescrever estado, descartar revisões, escolher
   fonte/limiar, abrir editor. **Nunca descartar trabalho commitado sem confirmar.**
3. **Determinístico**: o usuário escolhe mineral e método; a segmentação sai de código, nunca do "olho".
4. **Fonte por mineral** definida no config, escolhida por calibração. Princípios: **bruto inunda / fração
   isola**; elementos que não co-ocorrem por pixel → **região** (suavizado), não pixel.
5. **Pontos**: polígono (>4 pts = 1 região) ou semente (grão redondo por ponto).
6. **Propagação**: aprender do núcleo, limpar speckle, portão por região, usuário exclui as falsas.
7. **Backup/desfazer**: `rotulos_prev.npy` antes de gravar `rotulos.npy`.
8. **Contexto compacto**: dois runbooks (este = pipeline; `/S_MudMapStudio` = software), código sem redundância.
9. **Orçamento de tokens**: perto do limite, pausar de forma ordenada (registrar parada + próximo passo).

Ao concluir uma etapa, atualizar **Estado atual** (abaixo) — é o que o próximo operador vai ler.

## Estado atual (2026-09-30) — sítio ATIVO: 1.2 · repositório no GitHub conferido

**Arquivados e consistentes** (`estado/` = sítio 1.2; `sitios/1.1/` = sítio 1.1; pacotes
`saida/mudmap/RJS0649RJ_<s>.mudmap` = estado; importar os TIFFs reproduz cada pacote bit a bit;
`validar_nucleo.py` OK nos dois sítios):

| sítio | pixel / FOV | px rotulados | relatório (matriz → argila) | inspetor |
|---|---|---|---|---|
| 1.1 | 0,1089 µm / 111,5 µm, c/ Na | 408.858 | silte 19,8% · argila 80,2% (matriz biotita+clorita = 75,7%; 95 grãos; D50 1,51 µm) | https://claude.ai/artifact/8948mPsHdAz1nqqBwxTxo2 (v5) |
| 1.2 | 0,0544 µm / 55,8 µm, sem Na | 245.957 | argila 100% (matriz biotita = 68,7%; 15 grãos, todos < 3,9 µm; D50 1,60 µm) | https://claude.ai/artifact/SBu9519HHKhuChPGWFbAgs (v3) |

Relatórios: `saida/relatorio_final_<s>.png/.json` (regerados 2026-09-30, versionados). Links de inspetor =
artefatos da conta do autor (podem não abrir para outro operador; regerar com `exportar_graos.py`).
- **1.1** (2026-09-28): removidos os 13.807 px fora da máscara (furos da máscara dentro dos grãos gravados
  pelo bug do `limpar`); quartzo re-segmentado no MudMap Studio e exportado p/ estado (15:23; 6.840 objetos).
  No GitHub o `sitios/1.1/` foi reconstruído do pacote (rótulos + config); **clusters recalculados em
  2026-09-30** com o `reconhecer.py` atual (o k-means salvo era de uma rodada antiga). Backups extras da
  máquina original (`rotulos_prev_pre_clorita_regra.npy`, `rotulos_prev_biotita_desenho.npy`, `sitios/1.2/`)
  não estão no repositório.
- **1.2** (re-segmentado 2026-09-28 na escala µm, `--auto --substituir`): quartzo 296 px (Si puro +
  convexo), sulfato_ca 192.721 (regra Ca/S disseminado = cimento, ~28%; inclui a zona de anquerita),
  óxido Ti 697, óxido Fe 109, biotita 36.069 (região + forma), clorita 16.065 (Mg/Si). Estado anterior em
  `estado/rotulos_pre_escala_um.npy`. Óxidos NÃO re-segmentados (com d_min 0,67 µm o Fe sumiria). Decisões:
  anquerita, feldspato e pirita ausentes; Na fora (Na.tif era cópia do 1.1).

**▶ PRÓXIMO PASSO:** sítios **2, 3, 4** — **em espera**: o USUÁRIO vai organizar `EDS/2..4` em subpastas
`EDS/<n>/<n.k>/` (hoje planas, vários conjuntos `<El> Wt% Map Data <k>.tif`; 1,1 GB, fora do git). Pares BSE
(correlação): 2.2↔EI1 (FOV 1115 µm), 2.3↔EI2 (558, sem S), 2.4↔EI3 (139); 3.4↔EI4 e 3.8↔EI12 (55,8, sem S),
3.7↔EI9 (558), 3.5↔EI5/3.6↔EI7/3.9↔EI14 (13,9), 3.11↔EI17 (7,0); 4.1↔EI2 (279), 4.2↔EI3 (27,9, sem S),
4.3↔EI5 (55,8). Sugestão: 2.4, 3.8, 4.3 (folha `saida/conjuntos_eds_2a4.png`, na máquina original). Sem S →
sulfato/pirita indetectáveis. Em cada sítio: `pixel_um: auto`, decidir os minerais `matriz`; checar o aviso
`[escala]`. Depois: 1 ponto por sítio no ternário (Fase 5 do app).

### Referência — sítio 1.1 (8 minerais; px do estado atual)

| id | mineral | px | método final |
|----|---------|----|--------------|
| 1 | quartzo | 31.293 | **desenho** do operador (re-segmentado no Studio em 2026-09-28); config = pureza `Si>0.40 & Al<0.10 & K<0.10` (frac suav r=15, `v`) + convexo (Dice 0,82) |
| 2 | sulfato_ca | 65.048 | regra `Ca>0.12 & S>0.12`, disseminado (cimento fino; IoU 0,42 vs operador) |
| 3 | pirita | 365 | regra `S>0.20 & Fe>0.18 & Ca<0.15 & Si<0.15` + forma {close 1, maior, preencher} (grão inteiro) |
| 5 | oxido_ti | 1.498 | regra `Ti>0.18` (Ti bruto = ruído; resgate por Ti; IoU 0,60) |
| 6 | oxido_fe | 28.062 | regra `Fe>0.20` (Fe bruto inunda; resgate por Fe; IoU 0,49) |
| 9 | biotita | 54.981 | grupos Mg∩Al∩Si suav r=27 altos + Ca/S/Ti baixos + forma alongada (IoU 0,43 = teto físico); **matriz** |
| 12 | feldspato | 22.083 | grupos potássico (Al∩K) ∪ sódico (Al+Si, K baixo, Na_frac alta), por região (IoU 0,67) |
| 13 | clorita | 205.528 | grupos da biotita com Mg **<** q0,70, Si > q0,60, Ca/S/Ti < q0,75 + `Si-Mg`>0,15 (fundo contínuo); **matriz** |

Porquês que valem para outros sítios: feldspato e biotita **não co-ocorrem por pixel** → só por região;
as "lâminas" da biotita são a matriz argilosa pervasiva; **biotita (Mg↑) e clorita (Si↑) particionam a
matriz pela fronteira de Mg**; anquerita no 1.1 era só borda da zona de Ca; watershed na BSE p/ grãos
da matriz foi testado e descartado. Sem ilita/esmectita no 1.1 (decisão do usuário).

## Decisões duráveis

- **Ids do config**: 1 quartzo, 2 sulfato_ca, 3 pirita, 4 titanita, 5 oxido_ti, 6 oxido_fe, 7 anquerita,
  8 carbonato_ca, 9 biotita, 10 ilita, 11 esmectita, 12 feldspato, 13 clorita. Não reordenar (remapearia
  `rotulos.npy`); minerais novos entram por APPEND.
- **Na na fração** quando o mapa existe (sem_classe Na-rico = resina + não identificáveis); sem C/O na fração;
  resina removida pela máscara (Otsu da soma + resgate). Sem correção de carbono.
- **Tamanhos em µm** (2026-09-28): parâmetros físicos na config, px derivados por sítio; referência = 1.1.
- **Relatório final**: Shepard por Wentworth (argila < 3,9 µm, silte 3,9–62,5, areia ≥ 62,5; d = 2√(área/π));
  grãos = objetos de `rotulos.npy` ≥ `area_min` de minerais NÃO-matriz; **matriz → argila** (área inteira,
  fração fina não resolvida — decisão 2026-09-28; critério automático por mineral ou solidez não separa);
  objetos < `area_min` = cimento/fino (fora do ternário; separados no inspetor); areia truncada pelo FOV;
  feldspato por objeto no ternário Na-K-Ca; se d_min ≥ 3,9 µm a argila não é medida (`argila_medida`).
- **Licenças** (2026-09-30): código MIT; dados da amostra RJS0649RJ (EDS, rótulos, pacotes, relatórios)
  CC BY 4.0 — citar Mateus Andrade e Lorran Faria do Nascimento (`CITATION.cff`).
