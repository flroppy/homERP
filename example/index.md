---
id: h3yNhbsh
---
homERP is Enterprise Resource Planning (ERP) for the home!

[Source Code](https://git.flpy.link/floppy/homERP)

This is homERP's example data so you can try it out. Point `DATA_DIR` at this folder to browse it on a local instance:

```bash
DATA_DIR=example uvicorn src.main:app --reload
```

Browse into **Garage**, **Kitchen**, or **Office** below to see nested items, custom fields,
and markdown content in action.