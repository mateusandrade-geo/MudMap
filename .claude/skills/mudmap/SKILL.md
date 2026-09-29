---
name: mudmap
description: Segmentação e classificação mineral de mapas EDS (MEV-EDS, exportados do AZtec) de rochas sedimentares/lamitos com o pipeline determinístico do MudMap — reconhecimento por k-means, segmentação um mineral por vez pelas regras da config, revisão com o usuário por prévias PNG, calibração de regras, relatório granulométrico (Shepard/Wentworth), ternário Na-K-Ca de feldspatos e pacote .mudmap para o MudMap Studio. Use quando o usuário quiser segmentar/classificar minerais em mapas EDS, continuar a segmentação de um sítio, calibrar a regra de um mineral, gerar o relatório final ou trocar de sítio/amostra.
---

# MudMap — segmentação mineral por EDS, conduzida pelo Claude

## Princípio inegociável

A atribuição de mineral a cada pixel sai de **código determinístico** (regras de
`config/classificacao.yaml`, k-means, ou edições explícitas que o usuário pediu), **nunca** do
seu julgamento visual. Seu papel: rodar os scripts, mostrar as prévias, resumir as evidências
**numéricas** que eles imprimem ("região X: Si 0,86, cátions ≈ 0 → candidata a quartzo") e aplicar
exatamente o que o usuário decidir. Tudo fica reprodutível e auditável.

## 0. Preparar (uma vez por sessão)

1. **Código.** Você precisa da pasta do projeto (com `scripts/`, `app/`, `config/`).
   - Repositório já aberto (Claude Code): nada a fazer.
   - Só este `.md`: `git clone https://github.com/mateusandrade-geo/MudMap.git && cd MudMap`
     (sem git: baixe https://github.com/mateusandrade-geo/MudMap/archive/refs/heads/main.zip).
   - Skill enviada como `.zip` (pasta com `scripts/` ao lado deste arquivo, ex.: claude.ai): copie a
     pasta inteira para um diretório de trabalho gravável e use a cópia como raiz.
2. **Dependências:** `pip install -r requirements.txt` (o napari **não** é necessário neste fluxo).
3. **Rode tudo na raiz do projeto.** Os scripts usam caminhos relativos (`config/`, `estado/`,
   `saida/`, `pasta_dados`). Não é preciso `PYTHONPATH`.
4. **Dados:** `python scripts/ativar_sitio.py --listar` mostra os sítios, se têm rótulos e se os mapas
   existem. Confira antes de começar:
   - **Sítio ativo sem mapas** (coluna `mapas` = FALTA): ative um que tenha
     (`python scripts/ativar_sitio.py 1.1`) ou peça os TIFFs ao usuário.
   - **Dados novos do usuário:** um TIFF por elemento exportado do AZtec (`<El> Wt% ... .tif`) +
     `Electron Image N.tif`, numa pasta `EDS/<amostra>/<sítio>/`. Siga "Novo sítio" (seção 6).
   - **Só testar:** `python scripts/gerar_exemplo.py --sem-rotulos`, depois `cd exemplo` e rode os
     scripts como `python ../scripts/<script>.py` (o exemplo é um projeto separado e sintético).
5. **Mostrar imagens:** quando um script imprimir `>> Agente: EXIBA este PNG`, abra o arquivo e
   mostre ao usuário (no claude.ai, exiba a imagem; no Claude Code, leia-a e dê o caminho). Comente
   só os números que o script imprimiu, não impressões visuais.

## 1. Reconhecimento (não commita nada)

```bash
python scripts/reconhecer.py            # k-means (k=9) → estado/clusters.npy/.json + tabela de centros
python scripts/candidatos.py            # → estado/candidatos.json + saida/candidatos_previa.png
```

Mostre `saida/candidatos_previa.png` e a tabela (mineral, % de área, nº de grãos, composição
dominante). Cada cluster recebe o nome da **primeira** regra da config que o centro satisfaz;
"(mapa)" = candidato por mapa de elemento. Proponha a ordem da config (do mais distinto ao mais
ambíguo) e pergunte por qual mineral começar.

## 2. Segmentar um mineral por vez

Cada rodada só atua nos pixels **livres** (`rotulos == 0`), então a ordem importa. Para cada mineral:

1. **Prévia:** `python scripts/segmentar.py --mineral <m> --previa` → mostre
   `saida/previa_<m>_pre.png`; informe px candidatos, px livres e a fonte (`regra`/`mapa`/`cluster`).
2. **Commit** (só com o OK do usuário): `python scripts/segmentar.py --mineral <m> --auto`.
   Aditivo: soma pixels livres, não invade outros minerais, backup em `estado/rotulos_prev.npy`,
   registra em `estado/progresso.json`. Para refazer um mineral do zero: `--substituir`.
   Opções úteis: `--fonte regra|mapa|cluster`, `--grupo <sub-modelo>`, `--limiar quantil --q-mapa 0.8`.
3. **Ajustes sem janela** (todos gravam backup de um passo em `estado/rotulos_prev.npy`):
   - remover grãos por número: `python scripts/revisar_commit.py --mineral <m>` → mostre
     `saida/revisar_<m>.png`, o usuário diz os números → `--remover "3 7 9"`;
   - remover um objeto que o usuário riscou de azul numa cópia da prévia:
     `python scripts/remover_objeto.py --imagem <png> [--cor "#3F48CC"]` (prévia) e depois `--aplicar`;
   - desenhar grãos com pontos coloridos numa imagem (ex.: Paint):
     `python scripts/revisar_pontos.py --mineral <m> --imagem <png> --cor "#ff00ff" --modo convexo`
     (prévia) e depois `--commit` (substitui o mineral); `--modo semente` = um ponto no centro de cada grão redondo.
4. **Desfazer o último passo:** copie `estado/rotulos_prev.npy` sobre `estado/rotulos.npy`
   (confirme com o usuário; só há **um** nível de desfazer).
5. **Conferir o todo:** `python scripts/mapa_atual.py [--base bse] [--apenas quartzo,pirita]` →
   `saida/previa_atual.png`.

Com tela, o **MudMap Studio** faz o mesmo com pincel, polígono, balde, propagar etc.
(`MudMapStudio.bat` no Windows, `./mudmap_studio.sh` no Linux/macOS; "Exportar p/ estado" grava
em `estado/rotulos.npy` com backup). Os editores napari antigos (`segmentar.py` sem `--auto`,
`editor_completo.py`, `propagar.py`, `revisar_regioes.py`) exigem `requirements-napari.txt`.

## 3. Calibrar a regra de um mineral

Quando o que o usuário marcou (commitado) e o candidato automático divergem:

```bash
python scripts/comparar.py --mineral <m> [--fonte regra|mapa|cluster] --calibrar
```

Mostre `saida/comparar_<m>.png` (TP verde, FP vermelho, FN azul) e reporte IoU, Dice, precisão,
recall e a **regra proposta** (também em `saida/calibra_<m>.json`). Limiares vêm de dados (grãos de
referência, histogramas), nunca de chute. **Nunca edite `config/classificacao.yaml` sem confirmação
explícita.** Ao editar: mude só o bloco do mineral, preserve os comentários e registre no comentário
a data, contra o que foi calibrado e a métrica (como os blocos existentes fazem).

## 4. Resultados

| Comando | Saída |
|---|---|
| `python scripts/exportar_graos.py` | `saida/graos/index.html` — inspetor HTML interativo (com `graos_bse.png`, `graos_idmap.png` e `graos.json` ao lado; o MudMap Studio exporta a versão em arquivo único) |
| `python scripts/relatorio_final.py --previa` | `saida/relatorio_final_previa.png` + `.json`: Shepard, D50, por mineral, Na-K-Ca |
| `python scripts/exportar_mudmap.py [--todos]` | `saida/mudmap/<amostra>_<sítio>.mudmap` (abre no MudMap Studio) |
| `python scripts/arquivar_sitio.py` | prévia final + inspetor + snapshot do sítio em `sitios/<s>/` |
| `python scripts/ancorar_centros_bse.py` | centros dos grãos na BSE, com ajuste no napari → `saida/centros_bse.csv/.json` |

## 5. Config de classificação (`config/classificacao.yaml`)

- Cabeçalho do sítio: `amostra`, `elementos` (sem O e C), `sitio`, `pasta_dados`, `bse`,
  `pixel_um` (`auto` = lê `<PixelWidth_um>` do TIFF), `d_min_um` (menor grão, µm), `corte_fundo`
  (`null` = Otsu).
- `minerais`: a **ordem é a prioridade** e o id de cada mineral é a posição (1..N) — é o valor
  gravado em `rotulos.npy`, então **não reordene nem remova minerais** de um projeto com rótulos
  (acrescente no fim).
- Por mineral: `condicoes` (E lógico sobre frações de cátion: `">0.30"`, `"<0.10"`, faixa
  `"0.08 - 0.20"`; canal = elemento, `A+B`, `A-B` ou `A/B`), `fonte_default`, `mapas_seg` +
  `mapas_modo`/`mapas_limiar`/`mapas_q`, `mapas_grupos` (união de sub-modelos por região sobre mapas
  suavizados: `{canal, tipo: raw|frac, op, q|v}`), `suavizar_um`, `forma` (`close_um`, `d_min_um`,
  `ecc_min`, `convex`, `maior`, `preencher`), `disseminado` (não limpa por área), `matriz` (não é
  grão; entra inteira na argila), `feldspato` (vai para o ternário Na-K-Ca), `cor`.
- Tamanhos em µm viram px pelo `pixel_um` do sítio em `common.resolver_escala` (um só lugar).

## 6. Trocar de sítio / novo sítio

- **Trocar para um sítio arquivado:** `python scripts/arquivar_sitio.py` (arquivamento completo do
  ativo) e depois `python scripts/ativar_sitio.py <s>` (restaura `sitios/<s>/estado` e a config dele;
  guarda antes o ativo). Nada é apagado.
- **Novo sítio:** (1) `python scripts/arquivar_sitio.py`; (2) coloque os TIFFs em
  `EDS/<amostra>/<sítio>/`; (3) edite só o cabeçalho da config (`sitio`, `pasta_dados`, `bse`,
  `pixel_um: auto`, `elementos` presentes na pasta); (4) esvazie `estado/` (os arquivos já estão
  em `sitios/<antigo>/estado/`); (5) recomece pela seção 1. As regras são mantidas: reavalie cada
  mineral com prévias e, se preciso, recalibre (seção 3).

## Convenções

- Coordenadas **(row, col)** = (y, x), como no napari e no scipy.
- "Presente" ≈ fração de cátion `> 0.08`; "ausente/traço" ≈ `< 0.03`; a faixa intermediária fica
  sem classe de propósito (pixels mistos de borda → revisar).
- O e C fora das frações de cátion (O é discriminador fraco no EDS; C vem da resina).
- Discriminadores importam: p.ex. clorita × biotita pelo K e pelo Mg/Si (ver comentários da config).
- Granulometria (Wentworth, por diâmetro equivalente): argila < 3,9 µm ≤ silte < 62,5 µm ≤ areia;
  frações por área; minerais `matriz: true` somam na argila; grãos < `area_min` = cimento/finos,
  fora do ternário. Com FOV de ~56–111 µm, grãos de areia ficam truncados.
