use clap::Parser;
use quote::quote;
use std::fs;
use std::path::PathBuf;
use syn::{parse_file, File};

mod mutators;
mod ttdn;
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

    /// Force a particular mutation-candidate index (0-based) within the selected mutator.
    /// If out of range, the mutator will fall back to random selection.
    #[arg(long)]
    index: Option<usize>,

    /// Emit mutation-choice metadata to stderr as a single parseable line.
    /// Format: "MUTATION_CHOICE mode=<mode> count=<count> index=<index> mutated=<0|1>"
    #[arg(long, default_value_t = false)]
    emit_choice: bool,
}

fn main() {
    let args = Args::parse();
    
    let content = fs::read_to_string(&args.input).expect("Failed to read input file");
    let mut syntax_tree: File = match parse_file(&content) {
        Ok(f) => f,
        Err(e) => {
            // Many rustc tests intentionally use syntax that newer compilers accept
            // but `syn` may not yet parse. Don't panic; let the driver skip.
            eprintln!("Parse failed: {}", e);
            eprintln!("No mutation performed.");
            fs::write(&args.output, content).expect("Failed to write output file");
            return;
        }
    };

    // Unified TTDN metrics mode: emit JSON for the Python driver (seed selection/stagnation).
    // Keeps the same CLI contract (input/output/mode) to avoid changing callers.
    if args.mode.as_str() == "ttdn_metrics" {
        let info = crate::ttdn::TtdnInfo::from_file(&syntax_tree);
        let c = crate::ttdn::ConstraintChoiceMetrics::from_file(&syntax_tree);
        let payload = serde_json::json!({
            "constraint_sites": c.constraint_sites,
            "constraint_choice_sum": c.constraint_choice_sum,
            "traits": info.traits.len(),
            "types": info.types.len(),
            "impl_edges": info.impl_edges.len(),
            "supertrait_edges": info.supertrait_edges.len(),
            "trait_assoc_types": info.trait_assoc_types.len(),
            "impl_assoc_bindings": info.impl_assoc_bindings.len(),
        });
        println!("{}", payload.to_string());
        fs::write(&args.output, content).expect("Failed to write output file");
        return;
    }

    let (mutated, chosen_index, candidate_count) = match args.mode.as_str() {
        // Structural
        "add_assoc_type" => AddAssocTypeMutator.run_with_meta(&mut syntax_tree, args.index),
        "add_trait" => AddTraitMutator.run_with_meta(&mut syntax_tree, args.index),
        "add_impl" => AddImplMutator.run_with_meta(&mut syntax_tree, args.index),
        "constraint_injection" => ConstraintInjectionMutator.run_with_meta(&mut syntax_tree, args.index),
        
        // Non-Structural
        "bin_op_flip" => BinOpFlipMutator.run_with_meta(&mut syntax_tree, args.index),
        "int_literal_change" => IntLiteralChangeMutator.run_with_meta(&mut syntax_tree, args.index),
        "bool_flip" => BoolFlipMutator.run_with_meta(&mut syntax_tree, args.index),
        "replace_by_constant" => ReplaceByConstantMutator.run_with_meta(&mut syntax_tree, args.index),
        "inject_control_flow" => InjectControlFlowMutator.run_with_meta(&mut syntax_tree, args.index),
        
        _ => {
            eprintln!("Unknown mode: {}", args.mode);
            (false, 0, 0)
        }
    };

    if args.emit_choice {
        let m = if mutated { 1 } else { 0 };
        eprintln!(
            "MUTATION_CHOICE mode={} count={} index={} mutated={}",
            args.mode,
            candidate_count,
            chosen_index,
            m
        );
    }

    if mutated {
        eprintln!("Mutation successful.");
    } else {
        eprintln!("No mutation performed.");
    }

    // prettyplease can panic on newer/unsupported `syn` nodes (e.g. TypeParamBound::Verbatim).
    // Don't let formatting crash the whole mutation tool; fall back to token-based printing.
    // Note: even if we catch_unwind, the default panic hook prints to stderr; temporarily silence it.
    let prev_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    let mutated_content = match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        prettyplease::unparse(&syntax_tree)
    })) {
        Ok(s) => s,
        Err(_) => {
            eprintln!("prettyplease panicked; falling back to token-based output");
            quote!(#syntax_tree).to_string()
        }
    };
    std::panic::set_hook(prev_hook);
    fs::write(&args.output, mutated_content).expect("Failed to write output file");
}
