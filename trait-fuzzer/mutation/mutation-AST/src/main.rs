use clap::Parser;
use std::fs;
use std::path::PathBuf;
use syn::{parse_file, File};

mod mutators;
use mutators::structural::*;
use mutators::non_structural::*;
use mutators::framework::Mutator;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    #[arg(short, long)]
    input: PathBuf,

    #[arg(short, long)]
    output: PathBuf,

    #[arg(short, long)]
    mode: String,
}

fn main() {
    let args = Args::parse();
    
    let content = fs::read_to_string(&args.input).expect("Failed to read input file");
    let mut syntax_tree: File = parse_file(&content).expect("Failed to parse Rust code");

    let mutated = match args.mode.as_str() {
        // Structural
        "type_erasure" => TypeErasureMutator.run(&mut syntax_tree),
        "supertrait_expansion" => SupertraitExpansionMutator.run(&mut syntax_tree),
        "where_clause_expansion" => WhereClauseExpansionMutator.run(&mut syntax_tree),
        "trait_item_removal" => TraitItemRemovalMutator.run(&mut syntax_tree),
        "add_assoc_type" => AddAssocTypeMutator.run(&mut syntax_tree),
        "type_overwriting" => TypeOverwritingMutator.run(&mut syntax_tree),
        "generic_narrowing" => GenericNarrowingMutator.run(&mut syntax_tree),
        "add_trait" => AddTraitMutator.run(&mut syntax_tree),
        "add_generic_type" => AddGenericTypeMutator.run(&mut syntax_tree),
        
        // Non-Structural
        "bin_op_flip" => BinOpFlipMutator.run(&mut syntax_tree),
        "int_literal_change" => IntLiteralChangeMutator.run(&mut syntax_tree),
        "bool_flip" => BoolFlipMutator.run(&mut syntax_tree),
        "replace_by_constant" => ReplaceByConstantMutator.run(&mut syntax_tree),
        "inject_control_flow" => InjectControlFlowMutator.run(&mut syntax_tree),
        
        _ => {
            eprintln!("Unknown mode: {}", args.mode);
            false
        }
    };

    if mutated {
        eprintln!("Mutation successful.");
    } else {
        eprintln!("No mutation performed.");
    }

    let mutated_content = prettyplease::unparse(&syntax_tree);
    fs::write(&args.output, mutated_content).expect("Failed to write output file");
}
