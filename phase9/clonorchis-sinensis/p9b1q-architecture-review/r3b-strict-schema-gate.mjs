#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import YAML from "yaml";

const here = path.dirname(fileURLToPath(import.meta.url));
const schema = YAML.parse(fs.readFileSync(path.join(here, "negation-surface-scope-authority-schema-candidate.yml"), "utf8"));
const value = YAML.parse(fs.readFileSync(path.join(here, "negation-surface-scope-authority.yml"), "utf8"));
const ajv = new Ajv2020({allErrors: true, strict: true, validateFormats: false});
const validate = ajv.compile(schema);
const valid = validate(value);
process.stdout.write(JSON.stringify({
  gate_id: "p9b1q-r3b-ajv-draft2020-strict",
  draft: "2020-12",
  strict: true,
  compiled_schema_count: 1,
  valid_object_count: valid ? 1 : 0,
  result: valid ? "PASS" : "FAIL_CLOSED",
  errors: valid ? [] : validate.errors,
}));
process.exit(valid ? 0 : 1);
