# Entity Resolution Tool

## Overview
A LLM-aided probabilistic entity resolution and management tool for Enterprise legal uses. The tool processes legal insurance-related documents (PDFs or text) to generate a table of entities with auditability, explainability, and provenance.

## Files
- `test.py`: A script for testing the entity extraction functionality.
- `run.py`: The main script for running the entity extraction process on input data.

## Usage

### Running the Tool
1. **Install Dependencies**:
   ```sh
   pip install -r requirements.txt
   ```

2. **Run the Main Script**:
   ```sh
   python run.py --data_path <path_to_input_data> --chunk_size <chunk_size> --overlap <overlap_size> --seed <random_seed>
   ```
   Example:
   ```sh
   python run.py --data_path data/test-synthetic.txt --chunk_size 1500 --overlap 0 --seed 42
   ```
   

### Running the server
1. **start uvicorn server**:
   ```sh
    entity-res.venv/Scripts/activate
    uvicorn api.main:app --reload
   ```

2. **start npm**:
   ```sh
    cd frontend
    npm run dev
   ```

### Testing the Tool
1. **Run Tests**:
   ```sh
   python test.py
   ```

## Features

- **LLM Integration**: Uses a language model to extract entity names and types from legal documents.
- **Chunking and Overlap**: Efficiently processes large documents by splitting them into smaller chunks with overlap for better context.
- **Entity Normalization**: Cleans and normalizes extracted entities to ensure consistency.
- **Evaluation Metrics**: Provides detailed evaluation metrics comparing the extracted entities against ground truth data.

## Future Features

1. **Enhanced Entity Matching**: Improve entity matching algorithms to handle more complex cases.
2. **User Interface**: Develop a web-based interface for easier interaction with the tool.
3. **Advanced Logging and Auditing**: Implement more comprehensive logging and auditing features.
4. **Multi-Document Processing**: Support processing multiple documents at once.

## Contributing
Contributions are welcome! Please open an issue or submit a pull request if you find any bugs or have suggestions for improvements.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
