#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import YAML from "yaml";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "../../..");
const fixtures = path.join(here, "fixtures");
const readYaml = (p) => YAML.parse(fs.readFileSync(p, "utf8"));
const readJson = (p) => JSON.parse(fs.readFileSync(p, "utf8"));

const localSchemas = [
  "normalized-request-schema-candidate.yml",
  "clause-ast-schema-candidate.yml",
  "event-frame-schema-candidate.yml",
  "typed-solution-core-schema-candidate.yml",
  "typed-constraint-result-schema-candidate.yml",
  "queryir-emission-record-schema-candidate.yml",
  "minimality-proof-schema-candidate.yml",
  "constraint-id-registry-schema-candidate.yml",
  "constraint-set-schema-candidate.yml",
  "stage-semantic-validation-result-schema-candidate.yml",
  "execution-binding-sidecar-architecture-schema-candidate.yml",
  "reference-validator-execution-summary-schema-candidate.yml",
];
const externalSchemas = [
  path.join(repo, "phase9/clonorchis-sinensis/p9b1q/query-ir-schema-candidate.yml"),
  path.join(repo, "phase9/clonorchis-sinensis/request-schema.yml"),
];

const ajv = new Ajv2020({ allErrors: true, strict: true, validateFormats: false });
const byName = new Map();
const schemaUrlBase = "https://example.invalid/parasitology-kg/phase9/p9b1q/";
for (const name of localSchemas) {
  const schema = readYaml(path.join(here, name));
  byName.set(name, schema);
  ajv.addSchema(schema, name);
  const alias = structuredClone(schema);
  alias.$id = `${schemaUrlBase}${name}`;
  if (alias.$id !== schema.$id) ajv.addSchema(alias, alias.$id);
}
for (const absolute of externalSchemas) {
  const schema = readYaml(absolute);
  const name = path.basename(absolute);
  if (!ajv.getSchema(name) && !ajv.getSchema(schema.$id)) ajv.addSchema(schema, name);
  const alias = structuredClone(schema);
  alias.$id = absolute.endsWith("query-ir-schema-candidate.yml")
    ? `${schemaUrlBase}query-ir-schema-candidate.yml`
    : "https://example.invalid/parasitology-kg/phase9/request-schema.yml";
  if (!ajv.getSchema(alias.$id)) ajv.addSchema(alias, alias.$id);
}

const pairs = [
  ["normalized-request-schema-candidate.yml", "normalized-request-exposure-positive.json"],
  ["normalized-request-schema-candidate.yml", "normalized-request-diagnostic-positive.json"],
  ["clause-ast-schema-candidate.yml", "clause-ast-exposure-positive.json"],
  ["clause-ast-schema-candidate.yml", "clause-ast-diagnostic-positive.json"],
  ["event-frame-schema-candidate.yml", "event-frame-exposure-positive.json"],
  ["event-frame-schema-candidate.yml", "event-frame-diagnostic-positive.json"],
  ["typed-solution-core-schema-candidate.yml", "typed-solution-exposure-positive.json"],
  ["typed-constraint-result-schema-candidate.yml", "typed-result-exposure-positive.json"],
  ["queryir-emission-record-schema-candidate.yml", "queryir-emission-record-exposure-positive.json"],
  ...["M01", "M02", "E01", "R01", "N01", "N02", "Q01", "Q02"].map(
    (id) => ["minimality-proof-schema-candidate.yml", `minimality-removal-probe-${id}.json`],
  ),
  ["minimality-proof-schema-candidate.yml", "semantic-universe-exposure-positive.json"],
  ...["s0", "s1", "s2", "s3", "s4"].map(
    (stage) => ["stage-semantic-validation-result-schema-candidate.yml", `stage-validation-${stage}-positive.json`],
  ),
  ["execution-binding-sidecar-architecture-schema-candidate.yml", "execution-binding-sidecar-positive.json"],
  ["constraint-id-registry-schema-candidate.yml", "../constraint-id-registry.yml", "yaml"],
  ["constraint-set-schema-candidate.yml", "../constraint-set-v0.1.yml", "yaml"],
  ["reference-validator-execution-summary-schema-candidate.yml", "reference-validator-execution-summary.json"],
];

const results = [];
for (const [schemaName, fixtureName, format = "json"] of pairs) {
  const validate = ajv.getSchema(schemaName);
  if (!validate) throw new Error(`missing compiled schema ${schemaName}`);
  const absolute = path.resolve(fixtures, fixtureName);
  const value = format === "yaml" ? readYaml(absolute) : readJson(absolute);
  const valid = validate(value);
  results.push({
    schema: schemaName,
    fixture: path.relative(here, absolute),
    valid,
    errors: valid ? [] : validate.errors,
  });
}
const schemaArgIndex = process.argv.indexOf("--validate-schema");
if (schemaArgIndex >= 0) {
  const schemaName = process.argv[schemaArgIndex + 1];
  const validate = ajv.getSchema(schemaName);
  if (!validate) throw new Error(`missing compiled schema ${schemaName}`);
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const valid = validate(value);
  process.stdout.write(JSON.stringify({schema: schemaName, valid, errors: valid ? [] : validate.errors}));
  process.exit(valid ? 0 : 1);
}
const output = {
  gate_id: "p9b1q-ajv-draft2020-strict",
  ajv_version: JSON.parse(fs.readFileSync(path.join(here, "node_modules/ajv/package.json"), "utf8")).version,
  strict: true,
  compiled_schema_count: localSchemas.length,
  fixture_pair_count: pairs.length,
  valid_fixture_count: results.filter((x) => x.valid).length,
  result: results.every((x) => x.valid) ? "PASS" : "FAIL_CLOSED",
  results,
};
process.stdout.write(JSON.stringify(output));
process.exit(output.result === "PASS" ? 0 : 1);
