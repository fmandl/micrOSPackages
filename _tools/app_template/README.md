# 📦 micrOS Application: <package-app-name>

One-line summary of the package.

## Install

```bash
pacman install "<package-url>"
```

```bash
pacman upgrade "<package-app-name>"
pacman uninstall "<package-app-name>"
```

## Device Layout

- Package files: `/lib/<package-app-name>`
- Load modules: `/modules/LM_*`
- Web assets: `/web/*` when present

> Based on pacman.json

## Usage

```commandline
<app_name> load
<app_name> do
```

[documentation](https://htmlpreview.github.io/?https://github.com/BxNxM/micrOS/blob/master/micrOS/client/sfuncman/sfuncman.html#external-modules)

## Dependencies

Dependencies are auto installed by `mip` based on `package.json`

```text
n/a
```
