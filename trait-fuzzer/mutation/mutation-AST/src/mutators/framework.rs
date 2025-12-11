use syn::File;
use rand::Rng;

// Standard Mutator Interface
pub trait Mutator {
    // Step 1 & 2: Traverse and Collect candidates
    fn collect(&mut self, ast: &File) -> usize;

    // Step 4 & 5: Apply mutation to selected candidate
    fn mutate(&mut self, ast: &mut File, index: usize) -> bool;

    // Step 1-6 Driver (Standardized logic)
    fn run(&mut self, ast: &mut File) -> bool {
        // Step 1 & 2
        let count = self.collect(ast);
        if count == 0 {
            return false;
        }

        // Step 3: Select Mutation Instance
        let mut rng = rand::thread_rng();
        let index = rng.gen_range(0..count);

        // Step 4 & 5 & 6
        self.mutate(ast, index)
    }
}
